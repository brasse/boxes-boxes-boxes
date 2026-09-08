"""Engine construction, and the connection settings of §7.2."""

import sqlite3
from pathlib import Path
from typing import Any

import sqlalchemy
from sqlalchemy import Engine, event

# Applied to every connection, not once per database. foreign_keys in particular is
# per-connection and off by default, and without it the ON DELETE RESTRICT in the schema
# silently does nothing (§7.2).
PRAGMAS = (
    "PRAGMA foreign_keys = ON",
    "PRAGMA journal_mode = WAL",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA busy_timeout = 5000",
)


def create_engine(database_path: Path) -> Engine:
    engine = sqlalchemy.create_engine(
        f"sqlite+pysqlite:///{database_path}",
        connect_args={"check_same_thread": False},  # FastAPI runs these off the loop
    )
    event.listen(engine, "connect", apply_pragmas)
    return engine


def apply_pragmas(connection: sqlite3.Connection, _record: Any) -> None:
    cursor = connection.cursor()
    try:
        for pragma in PRAGMAS:
            cursor.execute(pragma)
    finally:
        cursor.close()
