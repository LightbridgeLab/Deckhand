"""Readable agent labels for the Agent Status dropdown."""

from __future__ import annotations

from deckhand.agents.base import friendly_agent_type, snippet
from deckhand.agents.claude_code import ClaudeCodeAgent
from deckhand.agents.cursor import CursorAgent
from deckhand.agents.mock import MockAgent
from deckhand.orchestrator.manager import Orchestrator


def test_friendly_agent_type() -> None:
    assert friendly_agent_type("claude_code") == "Claude"
    assert friendly_agent_type("claude-code") == "Claude"
    assert friendly_agent_type("cursor") == "Cursor"
    assert friendly_agent_type("mock") == "Demo"
    assert friendly_agent_type("external") == "External"


def test_snippet_collapses_and_truncates() -> None:
    assert snippet("  Please   review @CONFIG  ") == "Please review @CONFIG"
    long = "Please review @CONFIG.toml and the rest of this very long prompt"
    clipped = snippet(long)
    assert clipped.endswith("…")
    assert len(clipped) == 24


def test_claude_label_uses_project_folder() -> None:
    agent = ClaudeCodeAgent(
        agent_id="claude-code-9e77b92a",
        session_id="9e77b92a-full",
        project_root="/Users/dev/backend",
    )
    assert agent.display_label == "Claude: backend"
    assert agent.type_label == "Claude"


def test_claude_label_without_project_uses_short_id() -> None:
    agent = ClaudeCodeAgent(
        agent_id="claude-code-9e77b92a",
        session_id="9e77b92a-full",
    )
    assert agent.display_label == "Claude · 9e77b92a"


def test_cursor_label_uses_project_not_raw_prompt() -> None:
    agent = CursorAgent(
        agent_id="cursor-abcdef12",
        session_id="abcdef12xxxx",
        project_root="/Users/dev/Deckhand",
        title="Please review @CONFIG.toml for secrets",
    )
    assert agent.display_label == "Cursor: Deckhand"


def test_collision_appends_session_or_prompt() -> None:
    orch = Orchestrator()
    a1 = ClaudeCodeAgent(
        agent_id="claude-code-aaaaaaaa",
        session_id="aaaaaaaa-full",
        project_root="/tmp/backend",
    )
    a2 = ClaudeCodeAgent(
        agent_id="claude-code-bbbbbbbb",
        session_id="bbbbbbbb-full",
        project_root="/tmp/backend",
    )
    orch.register_agent(a1)
    orch.register_agent(a2)
    assert a1.display_label == "Claude: backend · aaaaaaaa"
    assert a2.display_label == "Claude: backend · bbbbbbbb"


def test_cursor_collision_uses_prompt_snippet() -> None:
    orch = Orchestrator()
    a1 = CursorAgent(
        agent_id="cursor-11111111",
        session_id="11111111xxxx",
        project_root="/tmp/Deckhand",
        title="Please review @CONFIG",
    )
    a2 = CursorAgent(
        agent_id="cursor-22222222",
        session_id="22222222xxxx",
        project_root="/tmp/Deckhand",
        title="Fix the focuser",
    )
    orch.register_agent(a1)
    orch.register_agent(a2)
    assert a1.display_label == "Cursor: Deckhand · Please review @CONFIG"
    assert a2.display_label == "Cursor: Deckhand · Fix the focuser"


def test_different_projects_are_not_disambiguated() -> None:
    orch = Orchestrator()
    a1 = MockAgent(agent_id="demo-1", project_root="/tmp/alpha")
    a2 = MockAgent(agent_id="demo-2", project_root="/tmp/beta")
    orch.register_agent(a1)
    orch.register_agent(a2)
    assert a1.display_label == "Demo: alpha"
    assert a2.display_label == "Demo: beta"
    assert a1.label_disambiguator is None
    assert a2.label_disambiguator is None
