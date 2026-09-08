"""Alembic environment.

The database URL comes from `boxes3.config` rather than from `alembic.ini`, so the CLI
and the application's own startup always target the same file (§9). When the application
runs migrations itself it passes its connection in through `config.attributes`, so both
paths go through the engine of §7.2 and its pragmas.

`render_as_batch` is on because SQLite's `ALTER TABLE` cannot do much beyond adding a
column, and batch mode rewrites the table instead (§7.5).
"""

from alembic import context
from sqlalchemy import Connection, Engine

from boxes3.config import Config
from boxes3.db.engine import create_engine
from boxes3.db.schema import metadata

target_metadata = metadata


def database_url() -> str:
    return f"sqlite+pysqlite:///{Config.load().database_path}"


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    injected = context.config.attributes.get("connection")
    if isinstance(injected, Connection):
        run_migrations(injected)
        return

    engine: Engine = create_engine(Config.load().database_path)
    with engine.connect() as connection:
        run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
