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
    Select,
    Text,
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
    UsernameTakenError,
    UserNotFoundError,
)
from boxes3.db.schema import boxes, item_tags, items, users
from boxes3.ids import new_public_id
from boxes3.models import Box, BoxUpdate, NewBox, Page, User

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
            return self._get_box(connection, username, box_id)

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
            matching = _box_filter(self._user_id(connection, username), q)
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
            box = self._get_box(connection, username, box_id)
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
            box = self._get_box(connection, username, box_id)
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
            statement = (
                select(boxes.c.number)
                .where(boxes.c.user_id == self._user_id(connection, username))
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
            statement = (
                select(boxes.c.location)
                .where(
                    boxes.c.user_id == self._user_id(connection, username),
                    boxes.c.location.is_not(None),
                    func.trim(boxes.c.location) != "",
                )
                .distinct()
                .order_by(boxes.c.location)
            )
            return list(connection.execute(statement).scalars().all())

    def _get_box(self, connection: Connection, username: str, box_id: str) -> Box:
        statement = _box_select().where(
            boxes.c.user_id == self._user_id(connection, username),
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
