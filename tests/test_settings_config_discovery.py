"""Tests for the config-file discovery order in deckhand.config.Settings.

Order under test:
1. ``DECKHAND_CONFIG_FILE`` env var (explicit override)
2. ``./config.toml`` (project-rooted)
3. ``~/.config/deckhand/config.toml`` (home-dir fallback)

First hit wins; later candidates are not merged. See settings.py docstring
on ``__init__`` for the rationale (OpenDeck-plugin-only installs).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckhand.config.settings import Settings


def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every DECKHAND_* env var that could leak from the dev shell."""
    for var in (
        "DECKHAND_CONFIG_FILE",
        "DECKHAND_HOST",
        "DECKHAND_PORT",
        "DECKHAND_PLUGINS",
        "DECKHAND_API_KEY",
        "DECKHAND_STATE_FILE",
        "DECKHAND_RATE_LIMIT_RPM",
        "DECKHAND_LOG_LEVEL",
        "DECKHAND_LOG_FORMAT",
        "DECKHAND_EVENT_LOG_ENABLED",
        "DECKHAND_EVENT_LOG",
    ):
        monkeypatch.delenv(var, raising=False)


def test_no_config_file_uses_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(fake_home))
    _isolate(monkeypatch)

    settings = Settings()
    assert settings.config_file_path is None
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000


def test_project_config_toml_is_picked_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "config.toml").write_text(
        '[service]\nhost = "from-project"\nport = 1111\n'
    )
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _isolate(monkeypatch)

    settings = Settings()
    assert settings.config_file_path == "config.toml"
    assert settings.host == "from-project"
    assert settings.port == 1111


def test_home_dir_config_is_picked_up_when_no_project_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """OpenDeck-plugin-only install: no service checkout, just a home-dir
    config.toml. The Settings loader should find it."""
    fake_home = tmp_path / "home"
    home_config_dir = fake_home / ".config" / "deckhand"
    home_config_dir.mkdir(parents=True)
    home_config = home_config_dir / "config.toml"
    home_config.write_text('[service]\nhost = "from-home"\nport = 2222\n')

    project = tmp_path / "project-without-config"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(fake_home))
    _isolate(monkeypatch)

    settings = Settings()
    assert settings.config_file_path == str(home_config)
    assert settings.host == "from-home"
    assert settings.port == 2222


def test_project_config_wins_over_home_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If both exist, the project-local config wins. No merging."""
    fake_home = tmp_path / "home"
    (fake_home / ".config" / "deckhand").mkdir(parents=True)
    (fake_home / ".config" / "deckhand" / "config.toml").write_text(
        '[service]\nhost = "from-home"\nport = 1\n'
    )

    project = tmp_path / "project"
    project.mkdir()
    (project / "config.toml").write_text('[service]\nhost = "from-project"\nport = 2\n')
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(fake_home))
    _isolate(monkeypatch)

    settings = Settings()
    assert settings.config_file_path == "config.toml"
    assert settings.host == "from-project"


def test_explicit_env_var_wins_over_both(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_home = tmp_path / "home"
    (fake_home / ".config" / "deckhand").mkdir(parents=True)
    (fake_home / ".config" / "deckhand" / "config.toml").write_text(
        '[service]\nhost = "from-home"\n'
    )

    project = tmp_path / "project"
    project.mkdir()
    (project / "config.toml").write_text('[service]\nhost = "from-project"\n')

    explicit = tmp_path / "explicit.toml"
    explicit.write_text('[service]\nhost = "from-explicit"\nport = 9999\n')

    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(fake_home))
    _isolate(monkeypatch)
    monkeypatch.setenv("DECKHAND_CONFIG_FILE", str(explicit))

    settings = Settings()
    assert settings.config_file_path == str(explicit)
    assert settings.host == "from-explicit"
    assert settings.port == 9999
