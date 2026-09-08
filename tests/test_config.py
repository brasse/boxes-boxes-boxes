import stat
import tomllib
from pathlib import Path

import pytest

from boxes3.config import Config, ConfigError
from boxes3.main import configure, create_directories

ENV_VARS = ("DATA_DIR", "SECRET_KEY", "BACKUP_TOKEN", "SESSION_COOKIE_SECURE")


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A data directory that does not exist yet, with the environment cleared."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(root))
    return root


def write_config(data_dir: Path, body: str) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "config.toml"
    path.write_text(body)
    return path


# Reading


def test_load_creates_nothing(data_dir: Path):
    config = Config.load()

    assert config.data_dir == data_dir
    assert not data_dir.exists()


def test_load_without_a_file_returns_defaults(data_dir: Path):
    config = Config.load()

    assert config.secret_key is None
    assert config.backup_token is None
    assert config.session_cookie_secure is False


def test_load_reads_the_file(data_dir: Path):
    write_config(
        data_dir,
        'secret_key = "k"\nbackup_token = "t"\nsession_cookie_secure = true\n',
    )

    config = Config.load()

    assert config.secret_key == "k"
    assert config.backup_token == "t"
    assert config.session_cookie_secure is True


def test_load_does_not_generate_a_secret_key(data_dir: Path):
    write_config(data_dir, 'backup_token = "t"\n')

    config = Config.load()

    assert config.secret_key is None
    assert config.config_path.read_text() == 'backup_token = "t"\n'


def test_a_wrongly_typed_string_raises(data_dir: Path):
    write_config(data_dir, "secret_key = 12345\n")

    with pytest.raises(ConfigError, match="secret_key must be a string"):
        Config.load()


def test_a_wrongly_typed_boolean_raises(data_dir: Path):
    write_config(data_dir, 'session_cookie_secure = "yes"\n')

    with pytest.raises(ConfigError, match="session_cookie_secure must be a boolean"):
        Config.load()


# Writing


def test_save_round_trips_through_load(data_dir: Path):
    data_dir.mkdir()
    saved = Config(data_dir, secret_key='a"b\\c', backup_token="t")
    saved.session_cookie_secure = True

    saved.save()
    loaded = Config.load()

    assert loaded == saved


def test_save_omits_absent_values(data_dir: Path):
    data_dir.mkdir()
    Config(data_dir, secret_key="k").save()

    with (data_dir / "config.toml").open("rb") as f:
        assert tomllib.load(f) == {"secret_key": "k", "session_cookie_secure": False}


def test_the_saved_file_is_readable_only_by_its_owner(data_dir: Path):
    data_dir.mkdir()
    Config(data_dir, secret_key="k").save()

    mode = stat.S_IMODE((data_dir / "config.toml").stat().st_mode)
    assert mode == 0o600, f"expected 0600, got {mode:o}"


def test_save_leaves_no_temporary_files(data_dir: Path):
    data_dir.mkdir()
    Config(data_dir, secret_key="k").save()

    assert sorted(p.name for p in data_dir.iterdir()) == ["config.toml"]


# Environment overrides, applied by load


def test_the_environment_wins_over_the_file(data_dir: Path, monkeypatch):
    write_config(data_dir, 'secret_key = "from-file"\nbackup_token = "from-file"\n')
    monkeypatch.setenv("SECRET_KEY", "from-env")
    monkeypatch.setenv("BACKUP_TOKEN", "from-env")

    config = Config.load()

    assert config.secret_key == "from-env"
    assert config.backup_token == "from-env"


def test_overrides_leave_the_file_alone(data_dir: Path, monkeypatch):
    path = write_config(data_dir, 'secret_key = "from-file"\n')
    monkeypatch.setenv("SECRET_KEY", "from-env")

    Config.load()

    assert path.read_text() == 'secret_key = "from-file"\n'


@pytest.mark.parametrize(
    ("value", "expected"),
    [("true", True), ("TRUE", True), (" True ", True), ("false", False)],
)
def test_session_cookie_secure_from_the_env(data_dir, monkeypatch, value, expected):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", value)

    assert Config.load().session_cookie_secure is expected


@pytest.mark.parametrize("value", ["sometimes", "1", "yes", "on", ""])
def test_an_unparseable_session_cookie_secure_raises(data_dir, monkeypatch, value):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", value)

    with pytest.raises(ConfigError, match="must be true or false"):
        Config.load()


# Directories and derived paths


def test_create_directories_makes_the_layout(data_dir: Path):
    config = Config.load()

    create_directories(config)

    assert config.blobs_dir.is_dir()
    assert config.tmp_dir.is_dir()
    assert config.backup_dir.is_dir()


def test_create_directories_is_idempotent(data_dir: Path):
    config = Config.load()

    create_directories(config)
    create_directories(config)

    assert config.blobs_dir.is_dir()


def test_the_paths_hang_off_the_data_directory(data_dir: Path):
    config = Config(data_dir)

    assert config.config_path == data_dir / "config.toml"
    assert config.blobs_dir == data_dir / "blobs"
    assert config.tmp_dir == data_dir / "tmp"
    assert config.backup_dir == data_dir / "backup"


# The startup sequence


def test_configure_generates_and_persists_a_key_on_first_run(data_dir: Path):
    config = configure()

    assert config.secret_key
    with config.config_path.open("rb") as f:
        assert tomllib.load(f)["secret_key"] == config.secret_key


def test_configure_creates_the_directories(data_dir: Path):
    config = configure()

    assert config.blobs_dir.is_dir()
    assert config.tmp_dir.is_dir()
    assert config.backup_dir.is_dir()


def test_configure_does_not_regenerate_the_key(data_dir: Path):
    first = configure()
    second = configure()

    assert first.secret_key == second.secret_key


def test_an_injected_key_is_not_written_to_disk(data_dir: Path, monkeypatch):
    """
    Injecting the key is a way of keeping it off disk (§9). Generating a second one
    into the file anyway would defeat that.
    """
    monkeypatch.setenv("SECRET_KEY", "injected")

    config = configure()

    assert config.secret_key == "injected"
    assert not config.config_path.exists()
    assert config.blobs_dir.is_dir()


def test_configure_defaults_the_data_directory_to_the_working_directory(
    tmp_path, monkeypatch
):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    config = configure()

    assert config.data_dir == Path("data")
    assert (tmp_path / "data" / "config.toml").is_file()
