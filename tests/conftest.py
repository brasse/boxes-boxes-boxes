import pytest

from boxes3.db.engine import create_engine
from boxes3.db.migrations import upgrade_to_head
from boxes3.db.sqlite import SqliteInventoryDatabase


@pytest.fixture
def db(tmp_path):
    """A migrated database, built the way production builds one."""
    engine = create_engine(tmp_path / "inventory.db")
    upgrade_to_head(engine)
    return SqliteInventoryDatabase(engine)


@pytest.fixture
def username(db):
    db.create_user("brasse", "hash")
    return "brasse"
