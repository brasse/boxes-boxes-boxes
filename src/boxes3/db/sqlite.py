"""The SQLite implementation of `InventoryDatabase`.

All SQL lives here (§7.4). Dialect-specific constructs are allowed inside this class and
nowhere else, and the cursor format is private to it: §6.0 makes cursors opaque, so what
they encode is not part of the contract.
"""

import base64
import binascii
import json
from datetime import UTC, datetime

from sqlalchemy import (
    ColumnElement,
    Connection,
    Engine,
    RowMapping,
    Select,
    Text,
    and_,
    cast,
    delete,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError

from boxes3.db.interface import (
    BoxNotEmptyError,
    BoxNotFoundError,
    BoxNumberTakenError,
    InvalidCursorError,
    InventoryDatabase,
    ItemNotFoundError,
    UsernameTakenError,
    UserNotFoundError,
)
from boxes3.db.schema import boxes, item_tags, items, users
from boxes3.ids import new_public_id
from boxes3.models import (
    Box,
    BoxSummary,
    BoxUpdate,
    Item,
    ItemUpdate,
    NewBox,
    NewItem,
    Page,
    TagCount,
    User,
)
from boxes3.tags import normalise

MAX_LIMIT = 200


class SqliteInventoryDatabase(InventoryDatabase):
    def __init__(self, engine: Engine):
        self.engine = engine

    # Users

    def create_user(self, username: str, password_hash: str) -> User:
        statement = (
            insert(users)
            .values(
                username=username,
                password_hash=password_hash,
                created_at=_now(),
            )
            .returning(*users.c)
        )
        try:
            with self.engine.begin() as connection:
                row = connection.execute(statement).mappings().one()
        except IntegrityError as error:
            raise UsernameTakenError(username) from error
        return User.model_validate(row)

    def get_user(self, username: str) -> User:
        statement = select(users).where(users.c.username == username)
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        if row is None:
            raise UserNotFoundError(username)
        return User.model_validate(row)

    def set_password(self, username: str, password_hash: str) -> User:
        statement = (
            update(users)
            .where(users.c.username == username)
            .values(password_hash=password_hash)
            .returning(*users.c)
        )
        with self.engine.begin() as connection:
            row = connection.execute(statement).mappings().first()
        if row is None:
            raise UserNotFoundError(username)
        return User.model_validate(row)

    # Boxes

    def create_box(self, username: str, box: NewBox) -> Box:
        with self.engine.connect() as connection:
            user_id = self._user_id(connection, username)

        statement = (
            insert(boxes)
            .values(
                public_id=new_public_id(),
                user_id=user_id,
                number=box.number,
                name=box.name,
                description=box.description,
                location=box.location,
                created_at=_now(),
            )
            .returning(*boxes.c)
        )
        try:
            with self.engine.begin() as connection:
                row = connection.execute(statement).mappings().one()
        except IntegrityError as error:
            raise _box_conflict(error, box.number) from error
        return Box.model_validate(row)

    def get_box(self, username: str, box_id: str) -> Box:
        with self.engine.connect() as connection:
            user_id = self._user_id(connection, username)
            return self._get_box(connection, user_id, box_id)

    def list_boxes(
        self,
        username: str,
        *,
        q: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> Page[Box]:
        limit = max(1, min(limit, MAX_LIMIT))
        after = _decode_cursor(cursor)

        with self.engine.connect() as connection:
            user_id = self._user_id(connection, username)
            matching = _box_filter(user_id, q)
            page = _box_select().where(*matching).order_by(boxes.c.number)
            if after is not None:
                page = page.where(boxes.c.number > after)

            rows = connection.execute(page.limit(limit + 1)).mappings().all()
            total = connection.execute(
                select(func.count()).select_from(boxes).where(*matching)
            ).scalar_one()

        entries = [Box.model_validate(row) for row in rows[:limit]]
        next_cursor = _encode_cursor(entries[-1].number) if len(rows) > limit else None
        return Page(entries=entries, total=total, next_cursor=next_cursor)

    def update_box(self, username: str, box_id: str, changes: BoxUpdate) -> Box:
        # exclude_unset, so an omitted field stays as it is while an explicit null
        # clears an optional one (§6.2).
        values = changes.model_dump(exclude_unset=True)
        if values.get("number", 1) is None:
            raise ValueError("number cannot be cleared")

        with self.engine.begin() as connection:
            user_id = self._user_id(connection, username)
            box = self._get_box(connection, user_id, box_id)
            if not values:
                return box

            statement = (
                update(boxes)
                .where(boxes.c.id == box.id)
                .values(**values)
                .returning(*boxes.c)
            )
            try:
                row = connection.execute(statement).mappings().one()
            except IntegrityError as error:
                raise _box_conflict(error, values.get("number")) from error

        return Box.model_validate({**dict(row), "item_count": box.item_count})

    def delete_box(self, username: str, box_id: str, *, force: bool = False) -> None:
        with self.engine.begin() as connection:
            user_id = self._user_id(connection, username)
            box = self._get_box(connection, user_id, box_id)
            if box.item_count and not force:
                raise BoxNotEmptyError(box.item_count)

            # item_tags has no ON DELETE CASCADE (§7.3), so its rows go first. All of
            # this is one transaction, so a failure part way leaves the box intact.
            held = select(items.c.id).where(items.c.box_id == box.id)
            connection.execute(delete(item_tags).where(item_tags.c.item_id.in_(held)))
            connection.execute(delete(items).where(items.c.box_id == box.id))
            connection.execute(delete(boxes).where(boxes.c.id == box.id))

    def next_box_number(self, username: str) -> int:
        with self.engine.connect() as connection:
            user_id = self._user_id(connection, username)
            statement = (
                select(boxes.c.number)
                .where(boxes.c.user_id == user_id)
                .order_by(boxes.c.number)
            )
            used = connection.execute(statement).scalars().all()

        # The lowest unused number, which is the first gap and not one past the end:
        # [1, 2, 4] gives 3, and [2, 3] gives 1. Walking a sorted list in lockstep with
        # a counter finds it, because the nth smallest number should be n and the first
        # place that fails is free. Reaching the end without a mismatch means the
        # numbers were exactly 1..len(used), so the answer is the next one up.
        #
        # Sorted by the query, distinct by UNIQUE (user_id, number).
        expected = 1
        for number in used:
            if number != expected:
                return expected
            expected += 1
        return expected

    def box_locations(self, username: str) -> list[str]:
        with self.engine.connect() as connection:
            user_id = self._user_id(connection, username)
            statement = (
                select(boxes.c.location)
                .where(
                    boxes.c.user_id == user_id,
                    boxes.c.location.is_not(None),
                    func.trim(boxes.c.location) != "",
                )
                .distinct()
                .order_by(boxes.c.location)
            )
            return list(connection.execute(statement).scalars().all())

    # Items

    def create_item(self, username: str, item: NewItem) -> Item:
        with self.engine.begin() as connection:
            user_id = self._user_id(connection, username)
            box_key = self._box_key(connection, user_id, item.box_id)
            now = _now()
            public_id = new_public_id()

            connection.execute(
                insert(items).values(
                    public_id=public_id,
                    user_id=user_id,
                    box_id=box_key,
                    title=item.title,
                    description=item.description,
                    created_at=now,
                    updated_at=now,
                )
            )
            item_key = connection.execute(
                select(items.c.id).where(items.c.public_id == public_id)
            ).scalar_one()
            _set_tags(connection, item_key, item.tags)

            return self._get_item(connection, user_id, public_id)

    def get_item(self, username: str, item_id: str) -> Item:
        with self.engine.connect() as connection:
            user_id = self._user_id(connection, username)
            return self._get_item(connection, user_id, item_id)

    def update_item(self, username: str, item_id: str, changes: ItemUpdate) -> Item:
        values = changes.model_dump(exclude_unset=True)

        with self.engine.begin() as connection:
            user_id = self._user_id(connection, username)
            item = self._get_item(connection, user_id, item_id)
            if not values:
                return item

            tags = values.pop("tags", None)
            if "title" in values and values["title"] is None:
                raise ValueError("title cannot be cleared")
            if "box_id" in values:
                target = values.pop("box_id")
                if target is None:
                    raise ValueError("box_id cannot be cleared")
                # Moving an item is just this: pointing it at another box (§6.3).
                values["box_id"] = self._box_key(connection, user_id, target)

            values["updated_at"] = _now()
            connection.execute(
                update(items).where(items.c.id == item.id).values(**values)
            )
            if tags is not None:
                _set_tags(connection, item.id, tags)

            return self._get_item(connection, user_id, item_id)

    def delete_item(self, username: str, item_id: str) -> None:
        with self.engine.begin() as connection:
            user_id = self._user_id(connection, username)
            item = self._get_item(connection, user_id, item_id)
            # The blobs stay where they are. Only gc removes bytes (§7.6).
            connection.execute(delete(item_tags).where(item_tags.c.item_id == item.id))
            connection.execute(delete(items).where(items.c.id == item.id))

    def search_items(
        self,
        username: str,
        *,
        q: str | None = None,
        tags: list[str] | None = None,
        box_id: str | None = None,
        has_image: bool | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> Page[Item]:
        limit = max(1, min(limit, MAX_LIMIT))
        after = _decode_item_cursor(cursor)

        with self.engine.connect() as connection:
            user_id = self._user_id(connection, username)
            matching = self._item_filter(
                connection, user_id, q, tags, box_id, has_image
            )

            page = (
                _item_select()
                .where(*matching)
                .order_by(items.c.updated_at.desc(), items.c.id.desc())
            )
            if after is not None:
                updated_at, item_key = after
                page = page.where(
                    or_(
                        items.c.updated_at < updated_at,
                        and_(items.c.updated_at == updated_at, items.c.id < item_key),
                    )
                )

            rows = connection.execute(page.limit(limit + 1)).mappings().all()
            total = connection.execute(
                select(func.count()).select_from(items).where(*matching)
            ).scalar_one()

            kept = list(rows[:limit])
            entries = _to_items(connection, kept)

        next_cursor = (
            _encode_item_cursor(kept[-1]["updated_at"], kept[-1]["id"])
            if len(rows) > limit
            else None
        )
        return Page(entries=entries, total=total, next_cursor=next_cursor)

    def list_tags(self, username: str) -> list[TagCount]:
        with self.engine.connect() as connection:
            user_id = self._user_id(connection, username)
            statement = (
                select(item_tags.c.tag, func.count().label("count"))
                .join_from(item_tags, items, item_tags.c.item_id == items.c.id)
                .where(items.c.user_id == user_id)
                .group_by(item_tags.c.tag)
                .order_by(func.count().desc(), item_tags.c.tag)
            )
            rows = connection.execute(statement).mappings().all()
        return [TagCount.model_validate(row) for row in rows]

    def _item_filter(
        self,
        connection: Connection,
        user_id: int,
        q: str | None,
        tags: list[str] | None,
        box_id: str | None,
        has_image: bool | None,
    ) -> list[ColumnElement[bool]]:
        """
        Structured filters stay separate from `q` and compose with it, so adding one
        later is purely additive (§6.3).
        """
        conditions: list[ColumnElement[bool]] = [items.c.user_id == user_id]

        if q:
            # Today `q` is a LIKE over title and tags. It is defined semantically, so
            # widening it later is not a breaking change (§6.3).
            pattern = f"%{q.lower()}%"
            conditions.append(
                or_(
                    func.lower(items.c.title).like(pattern),
                    items.c.id.in_(
                        select(item_tags.c.item_id).where(
                            func.lower(item_tags.c.tag).like(pattern)
                        )
                    ),
                )
            )

        # Conjunctive: one subquery per tag, so an item must carry all of them.
        # normalise, not a lenient variant: an unstorable tag cannot be dropped from a
        # conjunctive filter without widening the search, so it is rejected instead.
        for tag in normalise(tags or []):
            conditions.append(
                items.c.id.in_(
                    select(item_tags.c.item_id).where(item_tags.c.tag == tag)
                )
            )

        if box_id is not None:
            conditions.append(
                items.c.box_id == self._box_key(connection, user_id, box_id)
            )

        if has_image is not None:
            conditions.append(
                items.c.image_key.is_not(None)
                if has_image
                else items.c.image_key.is_(None)
            )

        return conditions

    def _get_item(self, connection: Connection, user_id: int, item_id: str) -> Item:
        statement = _item_select().where(
            items.c.user_id == user_id, items.c.public_id == item_id
        )
        row = connection.execute(statement).mappings().first()
        if row is None:
            raise ItemNotFoundError(item_id)
        return _to_items(connection, [row])[0]

    def _box_key(self, connection: Connection, user_id: int, box_id: str) -> int:
        """A box's public id to its internal key, for a foreign key column."""
        statement = select(boxes.c.id).where(
            boxes.c.user_id == user_id, boxes.c.public_id == box_id
        )
        box_key = connection.execute(statement).scalar_one_or_none()
        if box_key is None:
            raise BoxNotFoundError(box_id)
        return box_key

    def _get_box(self, connection: Connection, user_id: int, box_id: str) -> Box:
        statement = _box_select().where(
            boxes.c.user_id == user_id,
            boxes.c.public_id == box_id,
        )
        row = connection.execute(statement).mappings().first()
        if row is None:
            raise BoxNotFoundError(box_id)
        return Box.model_validate(row)

    def _user_id(self, connection: Connection, username: str) -> int:
        """
        The one place an external identifier becomes an internal key.

        An extra lookup on a unique index over a table with one row, which costs
        nothing and keeps the integer from ever leaving this module (§6.0).

        The rule for this class: every public method resolves the username once, at
        the top, into a local named `user_id`. Every private helper below takes that
        internal key. Resolving twice in one operation, or inline inside a query, is a
        drift worth correcting rather than following.
        """
        statement = select(users.c.id).where(users.c.username == username)
        user_id = connection.execute(statement).scalar_one_or_none()
        if user_id is None:
            raise UserNotFoundError(username)
        return user_id


def _now() -> str:
    """RFC 3339 UTC, because SQLite has no native datetime type (§7.2)."""
    return datetime.now(UTC).isoformat()


def _box_select() -> Select:
    item_count = (
        select(func.count(items.c.id))
        .where(items.c.box_id == boxes.c.id)
        .scalar_subquery()
        .label("item_count")
    )
    return select(*boxes.c, item_count)


def _box_filter(user_id: int, q: str | None) -> list[ColumnElement[bool]]:
    """`q` matches box number, name and location (§6.2)."""
    conditions = [boxes.c.user_id == user_id]
    if q:
        pattern = f"%{q.lower()}%"
        conditions.append(
            or_(
                func.lower(cast(boxes.c.number, Text)).like(pattern),
                func.lower(boxes.c.name).like(pattern),
                func.lower(boxes.c.location).like(pattern),
            )
        )
    return conditions


def _item_select() -> Select:
    """
    Items with their box summary joined in. An item is always in exactly one box (§4),
    so this is an inner join and cannot drop or duplicate a row.
    """
    return select(
        items.c.id,
        items.c.public_id,
        items.c.user_id,
        items.c.title,
        items.c.description,
        items.c.image_key,
        items.c.image_original_type,
        items.c.created_at,
        items.c.updated_at,
        boxes.c.public_id.label("box_public_id"),
        boxes.c.number.label("box_number"),
        boxes.c.name.label("box_name"),
        boxes.c.location.label("box_location"),
    ).join_from(items, boxes, items.c.box_id == boxes.c.id)


def _to_items(connection: Connection, rows: list[RowMapping]) -> list[Item]:
    """
    Attach tags to a page of rows.

    One extra query for the whole page rather than one per item. Joining tags into
    `_item_select` instead would multiply rows by tag count and make the page limit
    mean something other than a number of items.
    """
    tags = _tags_for(connection, [row["id"] for row in rows])
    return [
        Item(
            id=row["id"],
            public_id=row["public_id"],
            user_id=row["user_id"],
            title=row["title"],
            description=row["description"],
            image_key=row["image_key"],
            image_original_type=row["image_original_type"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            tags=tags.get(row["id"], []),
            box=BoxSummary(
                public_id=row["box_public_id"],
                number=row["box_number"],
                name=row["box_name"],
                location=row["box_location"],
            ),
        )
        for row in rows
    ]


def _tags_for(connection: Connection, item_keys: list[int]) -> dict[int, list[str]]:
    if not item_keys:
        return {}

    statement = (
        select(item_tags.c.item_id, item_tags.c.tag)
        .where(item_tags.c.item_id.in_(item_keys))
        .order_by(item_tags.c.tag)
    )
    grouped: dict[int, list[str]] = {}
    for item_key, tag in connection.execute(statement).all():
        grouped.setdefault(item_key, []).append(tag)
    return grouped


def _set_tags(connection: Connection, item_key: int, tags: list[str]) -> None:
    """Replace an item's tags wholesale. They arrive already normalised (§4)."""
    connection.execute(delete(item_tags).where(item_tags.c.item_id == item_key))
    if tags:
        connection.execute(
            insert(item_tags), [{"item_id": item_key, "tag": tag} for tag in tags]
        )


def _encode_item_cursor(updated_at: str, item_key: int) -> str:
    """
    Keyset on (updated_at, id). `updated_at` is not unique, so the internal key breaks
    ties and keeps the order total. Both are stored as written, and RFC 3339 strings of
    one format sort chronologically as text (§7.2).
    """
    raw = json.dumps({"u": updated_at, "i": item_key}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_item_cursor(cursor: str | None) -> tuple[str, int] | None:
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return str(payload["u"]), int(payload["i"])
    except (
        binascii.Error,
        UnicodeDecodeError,
        ValueError,
        TypeError,
        KeyError,
    ) as error:
        raise InvalidCursorError(cursor) from error


def _box_conflict(error: IntegrityError, number: int | None) -> Exception:
    """
    Turn a constraint violation into the domain exception for it.

    SQLite reports the columns rather than the constraint name: "UNIQUE constraint
    failed: boxes.user_id, boxes.number". Reading a driver message at all is exactly the
    kind of dialect-specific thing §7.4 confines to this module.
    """
    message = str(error.orig)
    if "boxes.user_id" in message and "boxes.number" in message:
        return BoxNumberTakenError(number)
    return error


def _encode_cursor(number: int) -> str:
    """
    Keyset rather than offset: the cursor names the last row seen, so a page cannot
    shift under a concurrent insert and hand back a duplicate or skip a row.
    """
    raw = json.dumps({"n": number}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> int | None:
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return int(json.loads(base64.urlsafe_b64decode(padded))["n"])
    except (
        binascii.Error,
        UnicodeDecodeError,
        ValueError,
        TypeError,
        KeyError,
    ) as error:
        raise InvalidCursorError(cursor) from error
