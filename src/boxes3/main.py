"""The FastAPI application, and the startup work it does before serving anything."""

import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from boxes3.config import Config


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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    app.state.config = configure()
    yield


app = FastAPI(title="Boxes Boxes Boxes", lifespan=lifespan)
