"""Applying migrations (§7.5).

Alembic owns schema creation and evolution, including on a fresh database: the first
run applies migrations rather than calling `create_all()`. Having both paths build
production schemas is how they drift.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Engine

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def upgrade_to_head(engine: Engine) -> None:
    """
    Bring the database behind `engine` up to the newest revision.

    The connection is handed to `env.py` rather than letting Alembic build its own, so
    the migration runs over the pragmas of §7.2 like everything else.
    """
    with engine.begin() as connection:
        config = alembic_config()
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def alembic_config() -> AlembicConfig:
    """
    Build the configuration in code rather than reading `alembic.ini`.

    The migrations ship inside the package, so this works from an installed wheel and
    from a container image, neither of which has the repository's `alembic.ini`.
    """
    config = AlembicConfig()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config
