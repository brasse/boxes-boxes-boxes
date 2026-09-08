"""Alembic's entry point.

This file is not imported as a module. Alembic *executes* it as a script on every
`alembic` command, after putting a `context` object in scope for it. So the job here is
to answer one question, "what database, and configured how", and then hand control back.
It is written once and then rarely touched again; the migrations themselves live in
`versions/`.

Two things are answered here rather than in `alembic.ini`:

- The database path comes from `boxes3.config`, so the CLI and the application always
  target the same file (§9).
- When the application runs migrations itself it passes its own connection in through
  `config.attributes`, so both paths go through the engine of §7.2 and its pragmas.

`render_as_batch` is on because SQLite's `ALTER TABLE` cannot do much beyond adding a
column, and batch mode rewrites the table instead (§7.5).
"""

from alembic import context
from sqlalchemy import Connection

from boxes3.config import Config
from boxes3.db.engine import create_engine
from boxes3.db.schema import metadata


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=metadata,
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    # Offline mode prints SQL to stdout instead of connecting, for someone who applies
    # DDL by hand. Nothing here does that, and silently doing nothing would be worse.
    raise RuntimeError("offline mode is not supported; run against the database")

injected = context.config.attributes.get("connection")
if isinstance(injected, Connection):
    _run_migrations(injected)
else:
    engine = create_engine(Config.load().database_path)
    with engine.connect() as connection:
        _run_migrations(connection)
