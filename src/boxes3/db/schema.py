"""The schema of §7.3, defined once and dialect-neutrally (§7.4).

One `MetaData`, portable column types, no raw DDL and nothing SQLite-only, so another
backend can build the identical shape from these same definitions. Alembic owns schema
creation in production; `metadata.create_all()` is for tests only (§7.5).
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
)

# SQLite cannot drop or alter a constraint by name, so Alembic rewrites the whole table
# in batch mode (§7.5). That only works if every constraint has a name, and leaving
# naming to chance is how a migration ends up unable to find what it is altering.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", Text, nullable=False, unique=True),
    Column("password_hash", Text, nullable=False),
    Column("created_at", Text, nullable=False),
)

boxes = Table(
    "boxes",
    metadata,
    Column("id", Integer, primary_key=True),
    # Unique rather than merely indexed: every request resolves a row by its public id,
    # so a duplicate would make one of the two permanently unreachable (§7.3).
    Column("public_id", Text, nullable=False, unique=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("number", Integer, nullable=False),
    Column("name", Text),
    Column("description", Text),
    Column("location", Text),
    Column("created_at", Text, nullable=False),
    CheckConstraint("number >= 1", name="number_positive"),
    # Composite on purpose: two users may each own a box 7, one user may not own two.
    UniqueConstraint("user_id", "number"),
)

items = Table(
    "items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("public_id", Text, nullable=False, unique=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    # RESTRICT, not CASCADE: deleting a box that still holds items is an error, and
    # forced deletion removes them explicitly in the same transaction (§6.2).
    Column(
        "box_id",
        Integer,
        ForeignKey("boxes.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("title", Text, nullable=False),
    Column("description", Text),
    # SHA-256 hex of the uploaded original. Deliberately not unique: identical uploads
    # hash identically, and two items may legitimately share one photo (§7.3).
    Column("image_key", Text),
    Column("image_original_type", Text),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    CheckConstraint("length(trim(title)) > 0", name="title_not_blank"),
    Index("ix_items_box_id", "box_id"),
    Index("ix_items_user_id", "user_id"),
)

# Tag strings live here directly rather than in a tags table: a tag *is* its string, so
# the extra table would hold an id and the string it replaced while every query gained a
# join. Revisit only if tags gain attributes of their own (§7.3).
item_tags = Table(
    "item_tags",
    metadata,
    Column("item_id", Integer, ForeignKey("items.id"), primary_key=True),
    Column("tag", Text, primary_key=True),
    Index("ix_item_tags_tag", "tag"),
)
