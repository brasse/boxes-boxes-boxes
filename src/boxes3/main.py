"""The FastAPI application, and the startup work it does before serving anything."""

import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine

from boxes3.config import Config
from boxes3.db.engine import create_engine
from boxes3.db.migrations import upgrade_to_head


def configure() -> Config:
    """
    The startup sequence of §9.

    Read the configuration, create the data directory, and generate a session key if
    there is not one yet. `Config` itself only reads and writes its file, so every
    decision and every side effect is here.
    """
    config = Config.load()
    create_directories(config)

    if config.secret_key is None:
        config.secret_key = secrets.token_urlsafe(32)
        config.save()

    return config


def create_directories(config: Config) -> None:
    """Create the data directory layout of §9. Idempotent."""
    for directory in (
        config.data_dir,
        config.blobs_dir,
        config.tmp_dir,
        config.backup_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def start_database(config: Config) -> Engine:
    """Open the database and bring it to the newest revision (§7.5)."""
    engine = create_engine(config.database_path)
    upgrade_to_head(engine)
    return engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    config = configure()

    app.state.config = config
    app.state.engine = start_database(config)
    yield


app = FastAPI(title="Boxes Boxes Boxes", lifespan=lifespan)
