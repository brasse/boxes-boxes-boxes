"""
The schema, the connection settings, and the migration that builds them.

Every test here uses a temp *file* database rather than `:memory:` (§10). WAL mode and
the pragmas of §7.2 are part of what is being tested, and they do not mean the same
thing for an in-memory database.
"""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, insert, text
from sqlalchemy.exc import IntegrityError

from boxes3.db.engine import create_engine
from boxes3.db.migrations import upgrade_to_head
from boxes3.db.schema import boxes, item_tags, items, metadata, users

NOW = "2026-09-08T12:00:00Z"


@pytest.fixture
def engine(tmp_path):
    """A migrated database, built the way production builds one."""
    engine = create_engine(tmp_path / "inventory.db")
    upgrade_to_head(engine)
    return engine


def add_user(engine: Engine, username: str = "brasse") -> int:
    with engine.begin() as connection:
        result = connection.execute(
            insert(users)
            .values(username=username, password_hash="x", created_at=NOW)
            .returning(users.c.id)
        )
        return result.scalar_one()


def add_box(
    engine: Engine, user_id: int, number: int = 1, public_id: str = "b1"
) -> int:
    with engine.begin() as connection:
        result = connection.execute(
            insert(boxes)
            .values(public_id=public_id, user_id=user_id, number=number, created_at=NOW)
            .returning(boxes.c.id)
        )
        return result.scalar_one()


def add_item(
    engine: Engine, user_id: int, box_id: int, public_id: str = "i1", **values
) -> int:
    with engine.begin() as connection:
        result = connection.execute(
            insert(items)
            .values(
                public_id=public_id,
                user_id=user_id,
                box_id=box_id,
                title=values.pop("title", "drill"),
                created_at=NOW,
                updated_at=NOW,
                **values,
            )
            .returning(items.c.id)
        )
        return result.scalar_one()


# Migrations


def test_the_migration_builds_exactly_what_the_metadata_describes(engine: Engine):
    """
    Guards the drift §7.5 warns about. Alembic builds production schemas and
    create_all() builds test ones, so nothing else would notice them diverging.
    """
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        differences = compare_metadata(context, metadata)

    assert differences == []


def test_the_migration_creates_every_table_and_index(engine: Engine):
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")
        ).all()

    names = {(row.type, row.name) for row in rows}
    assert ("table", "users") in names
    assert ("table", "boxes") in names
    assert ("table", "items") in names
    assert ("table", "item_tags") in names
    assert ("index", "ix_items_box_id") in names
    assert ("index", "ix_items_user_id") in names
    assert ("index", "ix_item_tags_tag") in names


def test_downgrade_removes_everything(engine: Engine, tmp_path):
    from alembic import command

    from boxes3.db.migrations import alembic_config

    with engine.begin() as connection:
        config = alembic_config()
        config.attributes["connection"] = connection
        command.downgrade(config, "base")

    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table'")
        ).all()

    remaining = {row.name for row in rows if not row.name.startswith("sqlite_")}
    assert remaining == {"alembic_version"}


# Connection settings, §7.2


@pytest.mark.parametrize(
    ("pragma", "expected"),
    [
        ("foreign_keys", 1),
        ("journal_mode", "wal"),
        ("synchronous", 1),
        ("busy_timeout", 5000),
    ],
)
def test_the_pragmas_are_applied(engine: Engine, pragma, expected):
    with engine.connect() as connection:
        value = connection.execute(text(f"PRAGMA {pragma}")).scalar()

    assert value == expected


def test_the_pragmas_are_applied_to_every_connection(engine: Engine):
    """
    foreign_keys is per connection, not per database, so a listener that ran once would
    leave later connections unprotected.
    """
    for _ in range(3):
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1


# Constraints, §7.3


def test_deleting_a_box_that_holds_items_raises(engine: Engine):
    """
    This is the test that proves foreign_keys is really on. Without the pragma the
    ON DELETE RESTRICT is silently ignored and the delete succeeds.
    """
    user_id = add_user(engine)
    box_id = add_box(engine, user_id)
    add_item(engine, user_id, box_id)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(boxes.delete().where(boxes.c.id == box_id))


def test_deleting_an_empty_box_is_fine(engine: Engine):
    user_id = add_user(engine)
    box_id = add_box(engine, user_id)

    with engine.begin() as connection:
        connection.execute(boxes.delete().where(boxes.c.id == box_id))

    with engine.connect() as connection:
        assert connection.execute(boxes.select()).all() == []


def test_one_user_may_not_own_two_box_sevens(engine: Engine):
    user_id = add_user(engine)
    add_box(engine, user_id, number=7, public_id="b7")

    with pytest.raises(IntegrityError):
        add_box(engine, user_id, number=7, public_id="b7-again")


def test_two_users_may_each_own_a_box_seven(engine: Engine):
    first = add_user(engine, "brasse")
    second = add_user(engine, "someone-else")

    add_box(engine, first, number=7, public_id="b7-first")
    add_box(engine, second, number=7, public_id="b7-second")

    with engine.connect() as connection:
        assert len(connection.execute(boxes.select()).all()) == 2


def test_a_box_number_below_one_is_rejected(engine: Engine):
    user_id = add_user(engine)

    with pytest.raises(IntegrityError):
        add_box(engine, user_id, number=0)


def test_a_blank_item_title_is_rejected(engine: Engine):
    user_id = add_user(engine)
    box_id = add_box(engine, user_id)

    with pytest.raises(IntegrityError):
        add_item(engine, user_id, box_id, title="   ")


def test_public_ids_are_unique(engine: Engine):
    user_id = add_user(engine)
    box_id = add_box(engine, user_id)
    add_item(engine, user_id, box_id, public_id="same")

    with pytest.raises(IntegrityError):
        add_item(engine, user_id, box_id, public_id="same")


def test_two_items_may_share_an_image_key(engine: Engine):
    """
    Identical uploads hash identically, so a UNIQUE here would reject the second item
    for no discoverable reason (§7.3).
    """
    user_id = add_user(engine)
    box_id = add_box(engine, user_id)

    add_item(engine, user_id, box_id, public_id="i1", image_key="abc123")
    add_item(engine, user_id, box_id, public_id="i2", image_key="abc123")

    with engine.connect() as connection:
        assert len(connection.execute(items.select()).all()) == 2


def test_an_item_cannot_carry_the_same_tag_twice(engine: Engine):
    user_id = add_user(engine)
    box_id = add_box(engine, user_id)
    item_id = add_item(engine, user_id, box_id)

    with engine.begin() as connection:
        connection.execute(insert(item_tags).values(item_id=item_id, tag="tools"))

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(insert(item_tags).values(item_id=item_id, tag="tools"))


def test_a_tag_cannot_reference_a_missing_item(engine: Engine):
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(insert(item_tags).values(item_id=999, tag="tools"))
