"""End-to-end tests for the Deckhand OpenDeck plugin.

Simulates the OpenDeck WebSocket protocol with a mock server
and verifies plugin event handling against a real Deckhand Core.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

# Add plugin source to path
PLUGIN_DIR = Path(__file__).parent.parent / "com.deckhand.plugin.sdPlugin"
sys.path.insert(0, str(PLUGIN_DIR))

from actions.agent_status import STATUS_INDEX, AgentStatusHandler
from actions.widget import (
    WidgetHandler,
    _format_value,
    format_reset_flash_title,
    format_reset_remaining,
)
from bridge import DeckhandBridge

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_bridge():
    """DeckhandBridge with all methods mocked."""
    bridge = DeckhandBridge.__new__(DeckhandBridge)
    bridge.base_url = "http://localhost:8000"
    bridge.ws_url = "ws://localhost:8000/events"
    bridge._session = None

    bridge.list_agents = AsyncMock(
        return_value=[
            {"id": "mock-1", "type": "mock", "status": "idle", "capabilities": []},
            {"id": "mock-2", "type": "mock", "status": "running", "capabilities": []},
        ]
    )

    bridge.start_agent = AsyncMock()
    bridge.cancel_agent = AsyncMock()
    bridge.provide_input = AsyncMock()
    bridge.execute_action = AsyncMock()
    bridge.get_state = AsyncMock(
        return_value={"key": "test.key", "value": {"count": 42}}
    )
    bridge.list_state = AsyncMock(
        return_value=[
            {"key": "test.key", "value": {"count": 42}},
            {"key": "other.key", "value": {"active": True}},
        ]
    )
    bridge.list_state_key_catalog = AsyncMock(
        return_value={"config": None, "entries": []}
    )
    bridge.list_actions = AsyncMock(
        return_value=[
            {"name": "agents.focus_next_pending", "description": "Focus next pending"},
            {"name": "ui.open_url", "description": "Open a URL"},
        ]
    )
    bridge.close = AsyncMock()
    return bridge


@pytest.fixture
def mock_ws():
    """Mock WebSocket connection (simulates OpenDeck side)."""
    ws = AsyncMock()
    ws.send = AsyncMock()
    return ws


@pytest.fixture
def agent_handler(mock_bridge):
    return AgentStatusHandler(mock_bridge)


@pytest.fixture
def widget_handler(mock_bridge):
    return WidgetHandler(mock_bridge)


# ---------------------------------------------------------------------------
# AgentStatusHandler tests
# ---------------------------------------------------------------------------


class TestAgentStatusHandler:
    async def test_will_appear_fetches_status(
        self, agent_handler, mock_ws, mock_bridge
    ):
        """willAppear should fetch agent list and set initial state."""
        await agent_handler.on_will_appear(mock_ws, "ctx-1", {"agent_id": "mock-1"})

        mock_bridge.list_agents.assert_awaited_once()
        # Should have sent setState and setTitle
        calls = [json.loads(c.args[0]) for c in mock_ws.send.call_args_list]
        events = [c["event"] for c in calls]
        assert "setState" in events
        assert "setTitle" in events

    async def test_will_appear_no_agent(self, agent_handler, mock_ws):
        """willAppear with no agent_id shows 'No Agent'."""
        await agent_handler.on_will_appear(mock_ws, "ctx-1", {})

        calls = [json.loads(c.args[0]) for c in mock_ws.send.call_args_list]
        title_calls = [c for c in calls if c["event"] == "setTitle"]
        assert title_calls[0]["payload"]["title"] == "No Agent"

    async def test_will_disappear_removes_context(self, agent_handler, mock_ws):
        """willDisappear should unregister the context."""
        await agent_handler.on_will_appear(mock_ws, "ctx-1", {"agent_id": "mock-1"})
        assert "ctx-1" in agent_handler._watched

        await agent_handler.on_will_disappear("ctx-1")
        assert "ctx-1" not in agent_handler._watched

    async def test_key_down_starts_idle_agent(
        self, agent_handler, mock_ws, mock_bridge
    ):
        """Pressing a button for an idle agent should start it."""
        await agent_handler.on_key_down(mock_ws, "ctx-1", {"agent_id": "mock-1"})
        mock_bridge.start_agent.assert_awaited_once_with("mock-1")

    async def test_key_down_cancels_running_agent(
        self, agent_handler, mock_ws, mock_bridge
    ):
        """Pressing a button for a running agent should cancel it."""
        mock_bridge.list_agents.return_value = [
            {"id": "mock-1", "type": "mock", "status": "running", "capabilities": []},
        ]
        await agent_handler.on_key_down(mock_ws, "ctx-1", {"agent_id": "mock-1"})
        mock_bridge.cancel_agent.assert_awaited_once_with("mock-1")

    async def test_key_down_provides_input(self, agent_handler, mock_ws, mock_bridge):
        """Pressing a button for awaiting_input agent should send input."""
        mock_bridge.list_agents.return_value = [
            {
                "id": "mock-1",
                "type": "mock",
                "status": "awaiting_input",
                "capabilities": [],
            },
        ]
        await agent_handler.on_key_down(
            mock_ws,
            "ctx-1",
            {
                "agent_id": "mock-1",
                "default_input": "yes",
            },
        )
        mock_bridge.provide_input.assert_awaited_once_with("mock-1", "yes")

    async def test_deckhand_event_updates_context(self, agent_handler, mock_ws):
        """agent.status_changed event should update watched contexts."""
        # Register a context watching mock-1
        agent_handler._watched["ctx-1"] = {
            "agent_id": "mock-1",
            "sounds_enabled": False,
        }

        event = {
            "type": "agent.status_changed",
            "payload": {"agent_id": "mock-1", "status": "running"},
        }
        await agent_handler.on_deckhand_event(
            mock_ws, "agent.status_changed", event, {}
        )

        calls = [json.loads(c.args[0]) for c in mock_ws.send.call_args_list]
        state_calls = [c for c in calls if c["event"] == "setState"]
        assert state_calls[0]["payload"]["state"] == STATUS_INDEX["running"]

    async def test_deckhand_event_ignores_unwatched_agent(self, agent_handler, mock_ws):
        """Events for unwatched agents should be ignored."""
        agent_handler._watched["ctx-1"] = {
            "agent_id": "mock-1",
            "sounds_enabled": False,
        }

        event = {
            "type": "agent.status_changed",
            "payload": {"agent_id": "mock-999", "status": "error"},
        }
        await agent_handler.on_deckhand_event(
            mock_ws, "agent.status_changed", event, {}
        )
        mock_ws.send.assert_not_called()

    async def test_send_to_plugin_get_agents(self, agent_handler, mock_ws, mock_bridge):
        """Property Inspector getAgents request returns agent list."""
        await agent_handler.on_send_to_plugin(mock_ws, "ctx-1", {"type": "getAgents"})

        mock_bridge.list_agents.assert_awaited()
        calls = [json.loads(c.args[0]) for c in mock_ws.send.call_args_list]
        pi_calls = [c for c in calls if c["event"] == "sendToPropertyInspector"]
        assert len(pi_calls) == 1
        assert pi_calls[0]["payload"]["type"] == "agentList"
        assert "error" not in pi_calls[0]["payload"]
        assert len(pi_calls[0]["payload"]["agents"]) == 2
        assert pi_calls[0]["payload"]["core_url"] == mock_bridge.base_url

    async def test_send_to_plugin_get_agents_failure(
        self, agent_handler, mock_ws, mock_bridge
    ):
        """Failed getAgents still sends agentList with an error for the PI."""
        mock_bridge.list_agents.side_effect = RuntimeError("connection refused")

        await agent_handler.on_send_to_plugin(mock_ws, "ctx-1", {"type": "getAgents"})

        calls = [json.loads(c.args[0]) for c in mock_ws.send.call_args_list]
        pi_calls = [c for c in calls if c["event"] == "sendToPropertyInspector"]
        assert len(pi_calls) == 1
        payload = pi_calls[0]["payload"]
        assert payload["type"] == "agentList"
        assert payload["agents"] == []
        assert payload["error"] == "connection refused"
        assert payload["core_url"] == mock_bridge.base_url


# ---------------------------------------------------------------------------
# WidgetHandler tests
# ---------------------------------------------------------------------------


class TestWidgetHandler:
    async def test_will_appear_fetches_state(
        self, widget_handler, mock_ws, mock_bridge, monkeypatch, tmp_path
    ):
        """willAppear should fetch state, set title, and apply catalog image."""
        (tmp_path / "config.toml").write_text(
            "[catalog.state_keys]\n"
            "entries = [\n"
            '  { key = "test.key", dropdown_label = "Test", image = "claude" },\n'
            "]\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DECKHAND_CONFIG_FILE", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))

        await widget_handler.on_will_appear(
            mock_ws, "ctx-w1", {"state_key": "test.key"}
        )

        mock_bridge.get_state.assert_awaited_once_with("test.key")
        calls = [json.loads(c.args[0]) for c in mock_ws.send.call_args_list]
        events = [c["event"] for c in calls]
        assert "setImage" in events
        assert "setTitle" in events
        title_calls = [c for c in calls if c["event"] == "setTitle"]
        assert len(title_calls) == 1
        # value is {"count": 42}, single-key dict → show "42"
        assert title_calls[0]["payload"]["title"] == "42"
        image_calls = [c for c in calls if c["event"] == "setImage"]
        assert image_calls[0]["payload"]["image"].startswith("data:image/png;base64,")

    async def test_will_appear_no_key(self, widget_handler, mock_ws):
        """willAppear with no state_key shows 'No Key'."""
        await widget_handler.on_will_appear(mock_ws, "ctx-w1", {})

        calls = [json.loads(c.args[0]) for c in mock_ws.send.call_args_list]
        title_calls = [c for c in calls if c["event"] == "setTitle"]
        assert title_calls[0]["payload"]["title"] == "No Key"

    async def test_will_appear_missing_state(
        self, widget_handler, mock_ws, mock_bridge
    ):
        """willAppear with missing state key shows dash."""
        mock_bridge.get_state.return_value = None
        await widget_handler.on_will_appear(mock_ws, "ctx-w1", {"state_key": "nope"})

        calls = [json.loads(c.args[0]) for c in mock_ws.send.call_args_list]
        title_calls = [c for c in calls if c["event"] == "setTitle"]
        assert title_calls[0]["payload"]["title"] == "—"

    async def test_key_down_executes_action(self, widget_handler, mock_ws, mock_bridge):
        """Key press with press_mode=action executes configured action."""
        with patch("actions.widget.load_usage_reset_flash_seconds", return_value=0):
            await widget_handler.on_key_down(
                mock_ws,
                "ctx-w1",
                {
                    "press_mode": "action",
                    "action_on_press": "lights.toggle",
                    "action_payload": '{"room": 1}',
                },
            )
        mock_bridge.execute_action.assert_awaited_once_with(
            "lights.toggle", {"room": 1}
        )

    async def test_key_down_default_peek_skips_action(
        self, widget_handler, mock_ws, mock_bridge
    ):
        """Missing press_mode defaults to peek — action is not run."""
        with patch("actions.widget.load_usage_reset_flash_seconds", return_value=0):
            await widget_handler.on_key_down(
                mock_ws, "ctx-w1", {"action_on_press": "lights.toggle"}
            )
        mock_bridge.execute_action.assert_not_called()

    async def test_key_down_none_is_noop(self, widget_handler, mock_ws, mock_bridge):
        """press_mode=none does not peek or run an action."""
        widget_handler._watched["ctx-w1"] = {
            "state_key": "usage.claude_code.session",
            "display_format": "percentage",
            "value": {
                "short_label": "Session",
                "percent": 10.0,
                "resets_at": "2099-01-01T00:00:00+00:00",
            },
        }
        with patch("actions.widget.load_usage_reset_flash_seconds", return_value=5):
            await widget_handler.on_key_down(
                mock_ws,
                "ctx-w1",
                {"press_mode": "none", "action_on_press": "lights.toggle"},
            )
        mock_bridge.execute_action.assert_not_called()
        mock_ws.send.assert_not_called()

    async def test_key_down_no_action(self, widget_handler, mock_ws, mock_bridge):
        """Key press with no action configured does not execute an action."""
        with patch("actions.widget.load_usage_reset_flash_seconds", return_value=0):
            await widget_handler.on_key_down(
                mock_ws, "ctx-w1", {"press_mode": "action"}
            )
        mock_bridge.execute_action.assert_not_called()

    async def test_key_down_flashes_reset_remaining(
        self, widget_handler, mock_ws, mock_bridge
    ):
        """Press shows time-until-reset then restores the percentage title."""
        value = {
            "short_label": "Session",
            "percent": 29.0,
            "current": 29.0,
            "resets_at": "2026-08-14T12:00:00+00:00",
            "title": "Session\n29%",
        }
        widget_handler._watched["ctx-w1"] = {
            "state_key": "usage.antigravity.week",
            "display_format": "percentage",
            "value": value,
        }
        with (
            patch("actions.widget.load_usage_reset_flash_seconds", return_value=1),
            patch(
                "actions.widget.format_reset_remaining",
                return_value="2d 19h",
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await widget_handler.on_key_down(mock_ws, "ctx-w1", {"press_mode": "peek"})
            # Let the restore task run.
            task = widget_handler._flash_tasks.get("ctx-w1")
            assert task is not None
            await task

        calls = [json.loads(c.args[0]) for c in mock_ws.send.call_args_list]
        titles = [c["payload"]["title"] for c in calls if c["event"] == "setTitle"]
        assert titles[0] == "Session\n2d 19h"
        assert titles[-1] == "Session\n29%"

    async def test_key_down_both_runs_action_then_peek(
        self, widget_handler, mock_ws, mock_bridge
    ):
        value = {
            "short_label": "Session",
            "percent": 10.0,
            "resets_at": "2026-08-11T20:00:00+00:00",
        }
        widget_handler._watched["ctx-w1"] = {
            "state_key": "usage.claude_code.session",
            "display_format": "percentage",
            "value": value,
        }
        with (
            patch("actions.widget.load_usage_reset_flash_seconds", return_value=5),
            patch("actions.widget.format_reset_remaining", return_value="4h 0m"),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await widget_handler.on_key_down(
                mock_ws,
                "ctx-w1",
                {"press_mode": "both", "action_on_press": "lights.toggle"},
            )
            task = widget_handler._flash_tasks.get("ctx-w1")
            if task:
                await task
        mock_bridge.execute_action.assert_awaited_once_with("lights.toggle", {})

    async def test_key_down_action_error_shows_title(
        self, widget_handler, mock_ws, mock_bridge
    ):
        mock_bridge.execute_action.side_effect = RuntimeError("boom")
        widget_handler._watched["ctx-w1"] = {
            "state_key": "test.key",
            "display_format": "raw",
            "value": {"count": 7},
        }
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await widget_handler.on_key_down(
                mock_ws,
                "ctx-w1",
                {"press_mode": "action", "action_on_press": "lights.toggle"},
            )
        calls = [json.loads(c.args[0]) for c in mock_ws.send.call_args_list]
        titles = [c["payload"]["title"] for c in calls if c["event"] == "setTitle"]
        assert titles[0] == "Error"
        assert titles[-1] == "7"

    async def test_key_down_flash_disabled(self, widget_handler, mock_ws, mock_bridge):
        widget_handler._watched["ctx-w1"] = {
            "state_key": "usage.claude_code.session",
            "display_format": "percentage",
            "value": {
                "short_label": "Session",
                "percent": 10.0,
                "resets_at": "2026-08-11T20:00:00+00:00",
            },
        }
        with patch("actions.widget.load_usage_reset_flash_seconds", return_value=0):
            await widget_handler.on_key_down(mock_ws, "ctx-w1", {"press_mode": "peek"})
        mock_ws.send.assert_not_called()

    def test_format_reset_remaining_days_and_hours(self):
        now = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
        assert format_reset_remaining("2026-08-14T07:30:00+00:00", now=now) == "2d 19h"
        assert format_reset_remaining("2026-08-11T16:12:00+00:00", now=now) == "4h 12m"
        assert format_reset_remaining("2026-08-11T11:00:00+00:00", now=now) is None

    def test_format_reset_flash_title(self):
        title = format_reset_flash_title(
            {
                "short_label": "Session",
                "resets_at": "2099-01-01T00:00:00+00:00",
            }
        )
        assert title is not None
        assert title.startswith("Session\n")
        assert format_reset_flash_title({"short_label": "Session"}) is None
        titled = format_reset_flash_title(
            {
                "short_label": "On-demand",
                "resets_at": "2099-01-01T00:00:00+00:00",
            },
            "Demand",
        )
        assert titled is not None
        assert titled.startswith("Demand\n")

    async def test_deckhand_event_updates_widget(self, widget_handler, mock_ws):
        """state.changed event should update watched widget title."""
        widget_handler._watched["ctx-w1"] = {
            "state_key": "test.key",
            "display_format": "raw",
        }

        event = {
            "type": "state.changed",
            "payload": {"key": "test.key", "value": {"count": 99}},
        }
        await widget_handler.on_deckhand_event(mock_ws, "state.changed", event, {})

        calls = [json.loads(c.args[0]) for c in mock_ws.send.call_args_list]
        title_calls = [c for c in calls if c["event"] == "setTitle"]
        assert title_calls[0]["payload"]["title"] == "99"

    async def test_deckhand_event_ignores_other_keys(self, widget_handler, mock_ws):
        """state.changed for a different key should be ignored."""
        widget_handler._watched["ctx-w1"] = {
            "state_key": "test.key",
            "display_format": "raw",
        }

        event = {
            "type": "state.changed",
            "payload": {"key": "other.key", "value": {"x": 1}},
        }
        await widget_handler.on_deckhand_event(mock_ws, "state.changed", event, {})
        mock_ws.send.assert_not_called()

    async def test_send_to_plugin_get_state_keys_from_catalog(
        self, widget_handler, mock_ws, monkeypatch, tmp_path
    ):
        """getStateKeys reads [catalog.state_keys] from local config.toml."""
        (tmp_path / "config.toml").write_text(
            "[catalog.state_keys]\n"
            "entries = [\n"
            '  { key = "usage.claude_code.week", dropdown_label = "Claude: Week", format = "percentage", button_title = "Week" },\n'
            '  { key = "usage.claude_code.session", dropdown_label = "Claude: Session (5h)", format = "percentage", button_title = "Session" },\n'
            "]\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DECKHAND_CONFIG_FILE", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))

        await widget_handler.on_send_to_plugin(
            mock_ws, "ctx-w1", {"type": "getStateKeys"}
        )

        calls = [json.loads(c.args[0]) for c in mock_ws.send.call_args_list]
        pi_calls = [c for c in calls if c["event"] == "sendToPropertyInspector"]
        assert len(pi_calls) == 1
        payload = pi_calls[0]["payload"]
        assert payload["type"] == "stateKeyList"
        assert payload["source"] == "local"
        # Sorted by dropdown_label: Session before Week
        assert payload["keys"] == [
            {
                "key": "usage.claude_code.session",
                "dropdown_label": "Claude: Session (5h)",
                "format": "percentage",
                "button_title": "Session",
            },
            {
                "key": "usage.claude_code.week",
                "dropdown_label": "Claude: Week",
                "format": "percentage",
                "button_title": "Week",
            },
        ]
        mock_bridge = widget_handler.bridge
        mock_bridge.list_state_key_catalog.assert_not_called()

    async def test_send_to_plugin_get_actions(
        self, widget_handler, mock_ws, mock_bridge
    ):
        """getActions returns Core action list for the Action dropdown."""
        await widget_handler.on_send_to_plugin(
            mock_ws, "ctx-w1", {"type": "getActions"}
        )

        mock_bridge.list_actions.assert_awaited_once()
        calls = [json.loads(c.args[0]) for c in mock_ws.send.call_args_list]
        pi_calls = [c for c in calls if c["event"] == "sendToPropertyInspector"]
        assert len(pi_calls) == 1
        payload = pi_calls[0]["payload"]
        assert payload["type"] == "actionList"
        assert payload["actions"][0]["name"] == "agents.focus_next_pending"

    async def test_send_to_plugin_get_actions_failure(
        self, widget_handler, mock_ws, mock_bridge
    ):
        mock_bridge.list_actions.side_effect = RuntimeError("offline")
        await widget_handler.on_send_to_plugin(
            mock_ws, "ctx-w1", {"type": "getActions"}
        )
        calls = [json.loads(c.args[0]) for c in mock_ws.send.call_args_list]
        pi_calls = [c for c in calls if c["event"] == "sendToPropertyInspector"]
        assert pi_calls[0]["payload"]["type"] == "actionList"
        assert pi_calls[0]["payload"]["actions"] == []
        assert "offline" in pi_calls[0]["payload"]["error"]

    async def test_send_to_plugin_get_state_keys_falls_back_to_core(
        self, widget_handler, mock_ws, monkeypatch, tmp_path
    ):
        """When local catalog is empty, fetch from Core GET /catalog/state_keys."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DECKHAND_CONFIG_FILE", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))

        mock_bridge = widget_handler.bridge
        mock_bridge.list_state_key_catalog = AsyncMock(
            return_value={
                "config": "/proj/config.toml",
                "entries": [
                    {
                        "key": "usage.claude_code.session",
                        "dropdown_label": "Session",
                        "format": "percentage",
                        "button_title": "Sess",
                    },
                ],
            }
        )

        await widget_handler.on_send_to_plugin(
            mock_ws, "ctx-w1", {"type": "getStateKeys"}
        )

        calls = [json.loads(c.args[0]) for c in mock_ws.send.call_args_list]
        pi_calls = [c for c in calls if c["event"] == "sendToPropertyInspector"]
        assert pi_calls[0]["payload"]["source"] == "core"
        assert pi_calls[0]["payload"]["keys"] == [
            {
                "key": "usage.claude_code.session",
                "dropdown_label": "Session",
                "format": "percentage",
                "button_title": "Sess",
            }
        ]
        mock_bridge.list_state_key_catalog.assert_awaited_once()


# ---------------------------------------------------------------------------
# _format_value tests
# ---------------------------------------------------------------------------


class TestFormatValue:
    def test_raw_string(self):
        assert _format_value("hello", "raw") == "hello"

    def test_raw_number(self):
        assert _format_value(42, "raw") == "42"

    def test_currency(self):
        assert _format_value(1234.5, "currency") == "$1,234.50"

    def test_single_key_dict(self):
        assert _format_value({"count": 7}, "raw") == "7"

    def test_multi_key_dict_truncated(self):
        result = _format_value({"a": 1, "b": 2}, "raw")
        assert len(result) <= 12

    def test_long_string_truncated(self):
        result = _format_value("a" * 50, "raw")
        assert len(result) <= 12

    def test_summary_format(self):
        assert _format_value({"title": "4> 1?", "total": 5}, "summary") == "4> 1?"

    def test_usage_metric_number(self):
        value = {
            "label": "Session tokens (rolling)",
            "current": 12345,
            "max": 500000,
            "percent": 2.469,
            "unit": "tokens",
            "updated_at": 1710000000.0,
        }
        assert _format_value(value, "number") == "12,345"

    def test_usage_metric_raw(self):
        value = {
            "label": "Tokens (7d)",
            "current": 1500,
            "max": None,
            "percent": None,
            "unit": "tokens",
            "updated_at": 1710000000.0,
        }
        assert _format_value(value, "raw") == "1500"

    def test_usage_metric_percentage_with_cap(self):
        value = {
            "label": "Session tokens (rolling)",
            "current": 250,
            "max": 1000,
            "percent": 25.0,
            "unit": "tokens",
            "updated_at": 1710000000.0,
        }
        assert _format_value(value, "percentage") == "25%"

    def test_usage_metric_percentage_without_cap(self):
        value = {
            "label": "Tokens (7d)",
            "current": 1500,
            "max": None,
            "percent": None,
            "unit": "tokens",
            "updated_at": 1710000000.0,
        }
        assert _format_value(value, "percentage") == "—"

    def test_usage_metric_summary(self):
        value = {
            "label": "Session tokens (rolling)",
            "current": 42,
            "max": None,
            "percent": None,
            "unit": "tokens",
            "updated_at": 1710000000.0,
        }
        assert _format_value(value, "summary") == "Session toke"

    def test_plan_bar_percentage_two_line(self):
        value = {
            "label": "Current session",
            "short_label": "Session",
            "current": 36.0,
            "max": 100,
            "percent": 36.0,
            "unit": "percent",
            "title": "Session\n36%",
        }
        assert _format_value(value, "percentage") == "Session\n36%"

    def test_plan_bar_percentage_uses_button_title(self):
        value = {
            "short_label": "On-demand",
            "current": 12.0,
            "max": 100,
            "percent": 12.0,
            "unit": "percent",
        }
        assert _format_value(value, "percentage", "Demand") == "Demand\n12%"

    def test_plan_bar_summary_uses_title(self):
        value = {
            "label": "Current week (Fable)",
            "short_label": "Fable",
            "current": 60.0,
            "max": 100,
            "percent": 60.0,
            "unit": "percent",
            "title": "Fable\n60%",
        }
        assert _format_value(value, "summary") == "Fable\n60%"


# ---------------------------------------------------------------------------
# AgentSlotHandler tests
# ---------------------------------------------------------------------------


class TestAgentSlotHandler:
    async def test_slot_binds_highest_priority(self, mock_ws, mock_bridge):
        from actions.agent_slot import AgentSlotHandler

        mock_bridge.list_agents.return_value = [
            {
                "id": "cursor-aaa",
                "type": "cursor",
                "status": "running",
                "display_label": "proj",
                "updated_at": 2,
            },
            {
                "id": "cursor-bbb",
                "type": "cursor",
                "status": "awaiting_input",
                "display_label": "urgent",
                "updated_at": 1,
            },
        ]
        handler = AgentSlotHandler(mock_bridge)
        await handler.on_will_appear(
            mock_ws, "ctx-s1", {"slot_index": 1, "agent_filter": "cursor"}
        )

        calls = [json.loads(c.args[0]) for c in mock_ws.send.call_args_list]
        title_calls = [c for c in calls if c["event"] == "setTitle"]
        assert title_calls[-1]["payload"]["title"] == "Input!"

    async def test_slot_press_focuses_cursor(self, mock_ws, mock_bridge):
        from actions.agent_slot import AgentSlotHandler

        mock_bridge.list_agents.return_value = [
            {
                "id": "cursor-aaa",
                "type": "cursor",
                "status": "running",
                "updated_at": 1,
            },
        ]
        handler = AgentSlotHandler(mock_bridge)
        await handler.on_key_down(
            mock_ws, "ctx-s1", {"slot_index": 1, "agent_filter": "cursor"}
        )
        mock_bridge.execute_action.assert_awaited_once_with(
            "ui.focus_cursor_agent",
            {"agent_id": "cursor-aaa"},
        )


# ---------------------------------------------------------------------------
# AgentDashboardHandler smart press
# ---------------------------------------------------------------------------


class TestAgentDashboardSmartPress:
    async def test_press_focuses_attention_agent(self, mock_ws, mock_bridge):
        from actions.agent_dashboard import AgentDashboardHandler

        mock_bridge.list_agents.return_value = [
            {
                "id": "cursor-aaa",
                "type": "cursor",
                "status": "awaiting_input",
                "updated_at": 1,
            },
        ]
        handler = AgentDashboardHandler(mock_bridge)
        await handler.on_key_down(mock_ws, "ctx-d1", {"agent_filter": "cursor"})
        mock_bridge.execute_action.assert_awaited_once_with(
            "ui.focus_cursor_agent",
            {"agent_id": "cursor-aaa"},
        )
