"""Tests for the OpenDeck plugin's connection-config resolution.

Verifies the precedence chain documented in client_config.py:
env var → live runtime.toml → [client] → legacy deckhand.env → defaults.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).parent.parent / "com.deckhand.plugin.sdPlugin"
sys.path.insert(0, str(PLUGIN_DIR))

from client_config import (
    DEFAULT_URL,
    load_state_key_catalog,
    load_usage_reset_flash_seconds,
    resolve_connection,
)


def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "DECKHAND_URL",
        "DECKHAND_API_KEY",
        "DECKHAND_CONFIG_FILE",
        "DECKHAND_RUNTIME_FILE",
    ):
        monkeypatch.delenv(var, raising=False)


def test_no_sources_returns_default_url_and_no_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    _isolate(monkeypatch)

    url, api_key = resolve_connection(tmp_path / "no-plugin-here")
    assert url == DEFAULT_URL
    assert api_key is None


def test_env_var_wins_over_everything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Both [client] section and legacy deckhand.env are present, but the
    env var still wins."""
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "deckhand.env").write_text(
        "DECKHAND_URL=http://legacy:1\nDECKHAND_API_KEY=legacy\n"
    )
    project = tmp_path / "project"
    project.mkdir()
    (project / "config.toml").write_text(
        '[client]\nurl = "http://shared:2"\napi_key = "shared"\n'
    )
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _isolate(monkeypatch)
    monkeypatch.setenv("DECKHAND_URL", "http://env:3")
    monkeypatch.setenv("DECKHAND_API_KEY", "env-key")

    url, api_key = resolve_connection(plugin_dir)
    assert url == "http://env:3"
    assert api_key == "env-key"


def test_shared_config_used_when_env_var_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No env vars, [client] section present in ./config.toml → use it."""
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / "config.toml").write_text(
        '[client]\nurl = "http://shared:4"\napi_key = "shared-key"\n'
    )
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _isolate(monkeypatch)

    url, api_key = resolve_connection(plugin_dir)
    assert url == "http://shared:4"
    assert api_key == "shared-key"


def test_home_dir_config_used_when_no_project_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """OpenDeck-plugin-only install path: home-dir config carries [client]."""
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    fake_home = tmp_path / "home"
    (fake_home / ".config" / "deckhand").mkdir(parents=True)
    (fake_home / ".config" / "deckhand" / "config.toml").write_text(
        '[client]\nurl = "http://home:5"\napi_key = "home-key"\n'
    )
    project = tmp_path / "project-no-config"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(fake_home))
    _isolate(monkeypatch)

    url, api_key = resolve_connection(plugin_dir)
    assert url == "http://home:5"
    assert api_key == "home-key"


def test_live_runtime_wins_over_client_and_legacy_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "deckhand.env").write_text(
        "DECKHAND_URL=http://legacy:8000\nDECKHAND_API_KEY=legacy-key\n"
    )
    project = tmp_path / "project"
    project.mkdir()
    (project / "config.toml").write_text(
        '[client]\nurl = "http://stale:18765"\napi_key = "shared-key"\n'
    )
    runtime = tmp_path / "runtime.toml"
    runtime.write_text(
        f'url = "http://127.0.0.1:19000"\npid = {os.getpid()}\n', encoding="utf-8"
    )
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _isolate(monkeypatch)
    monkeypatch.setenv("DECKHAND_RUNTIME_FILE", str(runtime))

    url, api_key = resolve_connection(plugin_dir)
    assert url == "http://127.0.0.1:19000"
    assert api_key == "shared-key"


def test_dead_runtime_falls_back_to_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / "config.toml").write_text(
        '[client]\nurl = "http://from-client:18765"\napi_key = "shared-key"\n'
    )
    runtime = tmp_path / "runtime.toml"
    runtime.write_text(
        'url = "http://127.0.0.1:19000"\npid = 1000000000\n', encoding="utf-8"
    )
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _isolate(monkeypatch)
    monkeypatch.setenv("DECKHAND_RUNTIME_FILE", str(runtime))

    url, api_key = resolve_connection(plugin_dir)
    assert url == "http://from-client:18765"
    assert api_key == "shared-key"


def test_service_section_fills_url_when_client_omitted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A config with only [service] (the usual Core file) should still
    point the plugin at that listen address — not leftover deckhand.env."""
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "deckhand.env").write_text(
        "DECKHAND_URL=http://legacy:8000\nDECKHAND_API_KEY=legacy-key\n"
    )
    project = tmp_path / "project"
    project.mkdir()
    (project / "config.toml").write_text(
        '[service]\nhost = "127.0.0.1"\nport = 18765\n'
        '[auth]\napi_keys = [{ key = "from-auth", scope = "write" }]\n'
    )
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _isolate(monkeypatch)

    url, api_key = resolve_connection(plugin_dir)
    assert url == "http://127.0.0.1:18765"
    assert api_key == "from-auth"


def test_legacy_env_file_used_when_no_env_or_shared_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog
) -> None:
    """The deprecated deckhand.env fallback fires when nothing else has the
    values — and the plugin logs a deprecation warning."""
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "deckhand.env").write_text(
        "DECKHAND_URL=http://legacy:6\nDECKHAND_API_KEY=legacy-key\n"
    )
    project = tmp_path / "project-no-config"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _isolate(monkeypatch)

    with caplog.at_level(logging.WARNING):
        url, api_key = resolve_connection(plugin_dir)

    assert url == "http://legacy:6"
    assert api_key == "legacy-key"
    assert any("deprecated" in r.message for r in caplog.records)


def test_partial_env_var_is_filled_in_from_shared_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If only DECKHAND_URL is set in the environment, the api_key still
    comes from the [client] section. Values resolve independently — they
    don't have to come from the same tier."""
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / "config.toml").write_text(
        '[client]\nurl = "http://shared:7"\napi_key = "shared-key"\n'
    )
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _isolate(monkeypatch)
    monkeypatch.setenv("DECKHAND_URL", "http://env-only:8")

    url, api_key = resolve_connection(plugin_dir)
    assert url == "http://env-only:8"
    assert api_key == "shared-key"


def test_malformed_shared_config_is_logged_and_skipped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog
) -> None:
    """A broken [client] TOML must not crash the plugin — it should log
    the parse failure, skip the file, and try the next tier (legacy env
    file → defaults)."""
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / "config.toml").write_text("this is not [valid toml")
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _isolate(monkeypatch)

    with caplog.at_level(logging.WARNING):
        url, api_key = resolve_connection(plugin_dir)

    assert url == DEFAULT_URL
    assert api_key is None
    assert any("Could not read shared config" in r.message for r in caplog.records)


def test_load_state_key_catalog_from_shared_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "config.toml").write_text(
        "[catalog.state_keys]\n"
        "entries = [\n"
        '  { key = "usage.claude_code.session", dropdown_label = "Claude session (5h)", format = "percentage", button_title = "Session" },\n'
        '  { key = "agents.pending_input_count" },\n'
        "]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _isolate(monkeypatch)

    entries, path = load_state_key_catalog()
    assert path is not None
    assert path.endswith("config.toml")
    assert entries == [
        {
            "key": "usage.claude_code.session",
            "dropdown_label": "Claude session (5h)",
            "format": "percentage",
            "button_title": "Session",
        },
        {
            "key": "agents.pending_input_count",
            "dropdown_label": "agents.pending_input_count",
        },
    ]


def test_load_state_key_catalog_missing_section(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "config.toml").write_text(
        '[client]\nurl = "http://x"\n', encoding="utf-8"
    )
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _isolate(monkeypatch)

    entries, path = load_state_key_catalog()
    assert entries == []
    assert path is not None


def test_load_usage_reset_flash_seconds_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _isolate(monkeypatch)
    assert load_usage_reset_flash_seconds() == 5


def test_load_usage_reset_flash_seconds_from_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "config.toml").write_text(
        "[client]\nusage_reset_flash_seconds = 10\n", encoding="utf-8"
    )
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _isolate(monkeypatch)
    assert load_usage_reset_flash_seconds() == 10


def test_load_usage_reset_flash_seconds_zero_disables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "config.toml").write_text(
        "[client]\nusage_reset_flash_seconds = 0\n", encoding="utf-8"
    )
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _isolate(monkeypatch)
    assert load_usage_reset_flash_seconds() == 0
