"""Deckhand CLI entry point.

Run ``deckhand --help`` (after ``pip install -e .``) or ``python -m deckhand``.
"""

from __future__ import annotations

import typer

from deckhand.cli import config as cli_config
from deckhand.cli.client import DeckhandClient, DeckhandError
from deckhand.cli.commands import (
    actions as actions_cmd,
    agents as agents_cmd,
    events as events_cmd,
    hooks as hooks_cmd,
    signals as signals_cmd,
    state as state_cmd,
)
from deckhand.cli.formatters import emit_error

app = typer.Typer(
    help="Deckhand CLI — talk to a running Deckhand service.",
    add_completion=False,
    no_args_is_help=True,
)

state_app = typer.Typer(help="Inspect and watch the state store.", no_args_is_help=True)
events_app = typer.Typer(
    help="Stream the event bus or replay the JSONL log.", no_args_is_help=True
)
actions_app = typer.Typer(help="List and invoke actions.", no_args_is_help=True)
signals_app = typer.Typer(help="List and fire signals.", no_args_is_help=True)
agents_app = typer.Typer(help="Inspect and control agents.", no_args_is_help=True)
hooks_app = typer.Typer(
    help="Simulate Claude Code / Cursor hook payloads.", no_args_is_help=True
)

app.add_typer(state_app, name="state")
app.add_typer(events_app, name="events")
app.add_typer(actions_app, name="actions")
app.add_typer(signals_app, name="signals")
app.add_typer(agents_app, name="agents")
app.add_typer(hooks_app, name="hooks")


def _client(ctx: typer.Context) -> DeckhandClient:
    cfg: cli_config.CliConfig = ctx.obj["config"]
    return DeckhandClient(url=cfg.url, api_key=cfg.api_key)


def _run(ctx: typer.Context, fn) -> None:
    with _client(ctx) as client:
        try:
            fn(client)
        except DeckhandError as exc:
            emit_error(str(exc), exit_code=2)


@app.callback()
def root(
    ctx: typer.Context,
    url: str | None = typer.Option(
        None, "--url", help="Service URL (overrides env + config)."
    ),
    api_key: str | None = typer.Option(
        None, "--api-key", help="API key (overrides env + config)."
    ),
    config_file: str | None = typer.Option(
        None, "--config", help="Path to config.toml."
    ),
) -> None:
    ctx.obj = {"config": cli_config.load(url, api_key, config_file)}


# ---------------------------------------------------------------- state ----


@state_app.command("list")
def state_list(ctx: typer.Context) -> None:
    """List every state key currently in the store."""
    _run(ctx, lambda c: state_cmd.list_(c))


@state_app.command("get")
def state_get(ctx: typer.Context, key: str) -> None:
    """Print the JSON value for a state key."""
    _run(ctx, lambda c: state_cmd.get(c, key))


@state_app.command("watch")
def state_watch(
    ctx: typer.Context,
    key: str | None = typer.Argument(
        None, help="If set, only print state changes for this key."
    ),
) -> None:
    """Stream live state.changed events (Ctrl-C to stop)."""
    _run(ctx, lambda c: state_cmd.watch(c, key))


# ---------------------------------------------------------------- events ---


@events_app.command("tail")
def events_tail(
    ctx: typer.Context,
    type_filter: list[str] = typer.Option(
        [], "--type", "-t", help="Filter to events whose type matches one of these."
    ),
    from_log: bool = typer.Option(
        False,
        "--from-log",
        help="Read from the on-disk JSONL log instead of WebSocket.",
    ),
    follow: bool = typer.Option(
        True,
        "--follow/--no-follow",
        help="When reading from the log, keep tailing for new lines.",
    ),
) -> None:
    """Stream events from the live bus or from the JSONL log."""
    cfg: cli_config.CliConfig = ctx.obj["config"]
    if from_log:
        try:
            events_cmd.tail_log(cfg.event_log_path, type_filter, follow=follow)
        except FileNotFoundError:
            emit_error(
                f"event log not found at {cfg.event_log_path}. "
                "Enable it via [event_log] enabled = true in config.toml.",
                exit_code=2,
            )
        return
    _run(ctx, lambda c: events_cmd.tail_live(c, type_filter))


# ---------------------------------------------------------------- actions --


@actions_app.command("list")
def actions_list(ctx: typer.Context) -> None:
    """List every registered action with its payload schema."""
    _run(ctx, lambda c: actions_cmd.list_(c))


@actions_app.command("call")
def actions_call(
    ctx: typer.Context,
    name: str,
    payload: str = typer.Option("", "--payload", "-p", help="JSON payload object."),
) -> None:
    """Invoke an action by name."""
    _run(ctx, lambda c: actions_cmd.call(c, name, payload))


# ---------------------------------------------------------------- signals --


@signals_app.command("list")
def signals_list(ctx: typer.Context) -> None:
    """List every registered signal handler."""
    _run(ctx, lambda c: signals_cmd.list_(c))


@signals_app.command("fire")
def signals_fire(
    ctx: typer.Context,
    name: str,
    payload: str = typer.Option("", "--payload", "-p", help="JSON payload object."),
) -> None:
    """Fire a signal webhook."""
    _run(ctx, lambda c: signals_cmd.fire(c, name, payload))


# ---------------------------------------------------------------- agents ---


@agents_app.command("list")
def agents_list(ctx: typer.Context) -> None:
    """List every registered agent and its current status."""
    _run(ctx, lambda c: agents_cmd.list_(c))


@agents_app.command("start")
def agents_start(ctx: typer.Context, agent_id: str) -> None:
    """Start an agent."""
    _run(ctx, lambda c: agents_cmd.start(c, agent_id))


@agents_app.command("cancel")
def agents_cancel(ctx: typer.Context, agent_id: str) -> None:
    """Cancel a running agent."""
    _run(ctx, lambda c: agents_cmd.cancel(c, agent_id))


@agents_app.command("input")
def agents_input(ctx: typer.Context, agent_id: str, text: str) -> None:
    """Send a line of input to an agent awaiting input."""
    _run(ctx, lambda c: agents_cmd.input_(c, agent_id, text))


# ---------------------------------------------------------------- hooks ----


@hooks_app.command("simulate")
def hooks_simulate(
    ctx: typer.Context,
    agent_type: str = typer.Argument(..., help="One of: claude-code, cursor."),
) -> None:
    """Read a hook JSON payload from stdin and POST it to the matching endpoint."""
    _run(ctx, lambda c: hooks_cmd.simulate(c, agent_type))


if __name__ == "__main__":
    app()
