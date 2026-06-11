"""End-to-end tests for the Deckhand OpenDeck plugin.

Simulates the OpenDeck WebSocket protocol with a mock server
and verifies plugin event handling against a real Deckhand Core.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# Add plugin source to path
PLUGIN_DIR = Path(__file__).parent.parent / "com.deckhand.plugin.sdPlugin"
sys.path.insert(0, str(PLUGIN_DIR))

from actions.agent_status import AgentStatusHandler, STATUS_INDEX  # noqa: E402
from actions.widget import WidgetHandler, _format_value  # noqa: E402
from bridge import DeckhandBridge  # noqa: E402


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


# ---------------------------------------------------------------------------
# WidgetHandler tests
# ---------------------------------------------------------------------------


class TestWidgetHandler:
    async def test_will_appear_fetches_state(
        self, widget_handler, mock_ws, mock_bridge
    ):
        """willAppear should fetch state and set title."""
        await widget_handler.on_will_appear(
            mock_ws, "ctx-w1", {"state_key": "test.key"}
        )

        mock_bridge.get_state.assert_awaited_once_with("test.key")
        calls = [json.loads(c.args[0]) for c in mock_ws.send.call_args_list]
        title_calls = [c for c in calls if c["event"] == "setTitle"]
        assert len(title_calls) == 1
        # value is {"count": 42}, single-key dict → show "42"
        assert title_calls[0]["payload"]["title"] == "42"

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
        """Key press executes configured action."""
        await widget_handler.on_key_down(
            mock_ws, "ctx-w1", {"action_on_press": "lights.toggle"}
        )
        mock_bridge.execute_action.assert_awaited_once_with("lights.toggle", {})

    async def test_key_down_no_action(self, widget_handler, mock_ws, mock_bridge):
        """Key press with no action configured does nothing."""
        await widget_handler.on_key_down(mock_ws, "ctx-w1", {})
        mock_bridge.execute_action.assert_not_called()

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
