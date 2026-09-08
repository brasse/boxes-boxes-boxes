"""Configuration: `$DATA_DIR/config.toml` plus environment overrides (§9).

The file is the primary home, not the environment. `/data` is one mounted volume and
backup is a copy of it (§7.6), so a session key held only in a compose file would make
that copy silently incomplete: restoring onto another machine would invalidate every
session with no error explaining why.

This module knows how to read and write one file and where things sit under the data
directory. It creates nothing and decides nothing; the startup sequence in
`boxes3.main.configure` does that, out loud.
"""

import os
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILENAME = "config.toml"
DEFAULT_DATA_DIR = Path("data")

_HEADER = """\
# Boxes Boxes Boxes configuration (§9). Edit by hand; the app only writes this file
# when it generates a session key on first run.
#
# backup_token enables POST /api/admin/backup. Without it the endpoint does not exist.
"""


class ConfigError(Exception):
    """The configuration file or an environment override is not usable."""


@dataclass
class Config:
    """
    The settings of §9, plus the layout of the data directory they live in.

    The paths are derived rather than stored so that §9's directory listing has one
    home. Everything downstream asks this object where things go.
    """

    data_dir: Path
    secret_key: str | None = None
    backup_token: str | None = None
    session_cookie_secure: bool = False

    @classmethod
    def load(cls) -> Config:
        """
        Read `config.toml`, letting the environment override it (§9).

        Reads and nothing else: no key is generated, no file is written, no directory
        is created. Each field below shows its own precedence.
        """
        data_dir = Path(os.environ.get("DATA_DIR") or DEFAULT_DATA_DIR)
        values = _read(data_dir / CONFIG_FILENAME)

        return cls(
            data_dir=data_dir,
            secret_key=os.environ.get("SECRET_KEY") or _string(values, "secret_key"),
            backup_token=(
                os.environ.get("BACKUP_TOKEN") or _string(values, "backup_token")
            ),
            session_cookie_secure=_session_cookie_secure(values),
        )

    def save(self) -> None:
        """
        Write `config.toml` atomically, mode 0600.

        Atomic because a backup copies this directory and must never catch the file
        half-written (§9). `mkstemp` creates the temporary file 0600 and `os.replace`
        keeps that mode, so the permissions come for free.

        This writes what the object holds, including anything the environment
        supplied. It runs once, on first start, to persist a generated session key.
        The data directory has to exist already; creating it is startup's job.
        """
        fd, tmp_name = tempfile.mkstemp(
            dir=self.data_dir, prefix=".config-", suffix=".tmp"
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(self._toml())
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.config_path)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

    @property
    def config_path(self) -> Path:
        return self.data_dir / CONFIG_FILENAME

    @property
    def database_path(self) -> Path:
        return self.data_dir / "inventory.db"

    @property
    def blobs_dir(self) -> Path:
        return self.data_dir / "blobs"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backup"

    def _toml(self) -> str:
        """
        Serialise the settings.

        The standard library reads TOML but does not write it, and there are three
        settings, so a dependency to emit three lines is not worth it.
        """
        lines = [_HEADER]
        if self.secret_key is not None:
            lines.append(f"secret_key = {_quote(self.secret_key)}\n")
        if self.backup_token is not None:
            lines.append(f"backup_token = {_quote(self.backup_token)}\n")
        secure = "true" if self.session_cookie_secure else "false"
        lines.append(f"session_cookie_secure = {secure}\n")
        return "".join(lines)


def _read(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _session_cookie_secure(values: dict[str, object]) -> bool:
    """Default false, deliberately, so a fresh clone on http://localhost works (§5)."""
    override = os.environ.get("SESSION_COOKIE_SECURE")
    if override is not None:
        return _parse_bool("SESSION_COOKIE_SECURE", override)
    return _boolean(values, "session_cookie_secure")


def _quote(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _string(values: dict[str, object], key: str) -> str | None:
    value = values.get(key)
    if value is None or isinstance(value, str):
        return value
    raise ConfigError(f"{key} must be a string")


def _boolean(values: dict[str, object], key: str) -> bool:
    value = values.get(key, False)
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be a boolean")
    return value


def _parse_bool(name: str, value: str) -> bool:
    """Parse an environment override. In the file itself TOML has real booleans."""
    normalised = value.strip().lower()
    if normalised == "true":
        return True
    if normalised == "false":
        return False
    raise ConfigError(f"{name} must be true or false, not {value!r}")
