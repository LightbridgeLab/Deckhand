"""Deckhand CLI entry point.

Run ``deckhand --help`` (after ``pip install -e .``) or ``python -m deckhand``.
"""

from __future__ import annotations

from typing import Annotated

import typer

from deckhand.cli import config as cli_config
from deckhand.cli.client import DeckhandClient, DeckhandError
from deckhand.cli.commands import (
    actions as actions_cmd,
)
from deckhand.cli.commands import (
    agents as agents_cmd,
)
from deckhand.cli.commands import (
    catalog as catalog_cmd,
)
from deckhand.cli.commands import (
    events as events_cmd,
)
from deckhand.cli.commands import (
    hooks as hooks_cmd,
)
from deckhand.cli.commands import (
    signals as signals_cmd,
)
from deckhand.cli.commands import (
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
    help="Install and ingest session hooks (Claude Code / Cursor).",
    no_args_is_help=True,
)
catalog_app = typer.Typer(
    help="Maintain client catalogs in config.toml (e.g. Data Widget state keys).",
    no_args_is_help=True,
)

app.add_typer(state_app, name="state")
app.add_typer(events_app, name="events")
app.add_typer(actions_app, name="actions")
app.add_typer(signals_app, name="signals")
app.add_typer(agents_app, name="agents")
app.add_typer(hooks_app, name="hooks")
app.add_typer(catalog_app, name="catalog")


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
    type_filter: Annotated[
        list[str] | None,
        typer.Option(
            "--type", "-t", help="Filter to events whose type matches one of these."
        ),
    ] = None,
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
    filters = type_filter or []
    if from_log:
        try:
            events_cmd.tail_log(cfg.event_log_path, filters, follow=follow)
        except FileNotFoundError:
            emit_error(
                f"event log not found at {cfg.event_log_path}. "
                "Enable it via [event_log] enabled = true in config.toml.",
                exit_code=2,
            )
        return
    _run(ctx, lambda c: events_cmd.tail_live(c, filters))


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


@agents_app.command("demo")
def agents_demo(
    ctx: typer.Context,
    remove: bool = typer.Option(
        False,
        "--remove",
        help="Unregister the demo agent instead of creating it.",
    ),
) -> None:
    """Register a mock agent so Agent Status can be tested without IDE hooks."""
    _run(ctx, lambda c: agents_cmd.demo(c, remove=remove))


# ---------------------------------------------------------------- hooks ----


@hooks_app.command("ingest")
def hooks_ingest(
    ctx: typer.Context,
    agent_type: str = typer.Argument(..., help="One of: claude-code, cursor."),
    event: str | None = typer.Option(
        None,
        "--event",
        help="Cursor hook event name (required when stdin lacks hook_event_name).",
    ),
    status: str | None = typer.Option(
        None,
        "--status",
        help="Optional deckhand_status override (Cursor stop → awaiting_input).",
    ),
) -> None:
    """Read hook JSON from stdin and POST it to Deckhand (used by agent hooks)."""
    _run(
        ctx,
        lambda c: hooks_cmd.ingest(c, agent_type, event=event, status=status),
    )


@hooks_app.command("simulate")
def hooks_simulate(
    ctx: typer.Context,
    agent_type: str = typer.Argument(..., help="One of: claude-code, cursor."),
) -> None:
    """Like ingest, but print the Core response (for local testing)."""
    _run(ctx, lambda c: hooks_cmd.simulate(c, agent_type))


@hooks_app.command("install")
def hooks_install(
    ctx: typer.Context,
    target: Annotated[
        list[str] | None,
        typer.Argument(
            help="claude-code, cursor, and/or all (default: all).",
        ),
    ] = None,
) -> None:
    """Merge Deckhand ingest commands into Claude Code / Cursor hook files."""
    targets = target or ["all"]
    cfg: cli_config.CliConfig = ctx.obj["config"]
    hooks_cmd.install(targets, config_path=cfg.config_file_path)


@hooks_app.command("status")
def hooks_status(ctx: typer.Context) -> None:
    """Show whether Core is up, hooks are installed, and any last ingest error."""
    cfg: cli_config.CliConfig = ctx.obj["config"]
    with _client(ctx) as client:
        hooks_cmd.status(client, api_key=cfg.api_key)


# --------------------------------------------------------------- catalog ---


@catalog_app.command("list")
def catalog_list(ctx: typer.Context) -> None:
    """Show [catalog.state_keys] entries from config.toml."""
    cfg: cli_config.CliConfig = ctx.obj["config"]
    catalog_cmd.list_(cfg.config_file_path)


@catalog_app.command("sync")
def catalog_sync(
    ctx: typer.Context,
    no_live: bool = typer.Option(
        False,
        "--no-live",
        help="Do not merge keys from the live state store (seeds only).",
    ),
) -> None:
    """Seed/merge [catalog.state_keys] for enabled plugins (+ live keys).

    Existing labels are preserved. Missing curated keys and live store keys
    are appended. Creates config.toml if needed.
    """
    cfg: cli_config.CliConfig = ctx.obj["config"]
    if no_live:
        catalog_cmd.sync(None, cfg.config_file_path, include_live=False)
        return
    with _client(ctx) as client:
        catalog_cmd.sync(client, cfg.config_file_path, include_live=True)


if __name__ == "__main__":
    app()
