from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import (
    Body,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from deckhand.agents.claude_code import ClaudeCodeAgent
from deckhand.agents.cursor import CursorAgent
from deckhand.agents.pending_input import PendingInputTracker
from deckhand.agents.summary import update_cursor_summary
from deckhand.config.settings import Settings
from deckhand.event_log import EventLogger
from deckhand.focusers.cursor import make_cursor_focuser
from deckhand.focusers.iterm import make_iterm_focuser
from deckhand.logging_config import configure_logging
from deckhand.metrics import Metrics
from deckhand.orchestrator.actions import ActionRegistry
from deckhand.orchestrator.events import build_error_event, build_event
from deckhand.orchestrator.manager import Orchestrator
from deckhand.orchestrator.signals import SignalRegistry
from deckhand.plugins.loader import load_plugins
from deckhand.plugins.registry import PluginRegistry
from deckhand.security import (
    ApiKeyEntry,
    RateLimiter,
    has_scope,
    resolve_key,
    validate_payload,
)

logger = logging.getLogger(__name__)

# Global instances (initialized in lifespan)
orchestrator: Orchestrator | None = None
action_registry: ActionRegistry | None = None
signal_registry: SignalRegistry | None = None
plugin_registry: PluginRegistry | None = None
settings: Settings | None = None
rate_limiter: RateLimiter | None = None
metrics: Metrics | None = None
_service_start_time: float | None = None

SERVICE_VERSION = "0.3.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    global \
        orchestrator, \
        action_registry, \
        signal_registry, \
        plugin_registry, \
        settings, \
        rate_limiter, \
        metrics, \
        _service_start_time

    _service_start_time = time.time()
    metrics = Metrics(started_at=_service_start_time)

    # Startup — load settings first so we can configure logging from them
    settings = Settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)
    logger.info("Starting Deckhand service...")

    # Log configuration
    logger.info("Configuration:")
    logger.info(f"  Host: {settings.host}")
    logger.info(f"  Port: {settings.port}")
    logger.info(f"  Config file: {settings.config_file_path or 'none'}")
    logger.info(f"  State file: {settings.state_file_path or 'none (in-memory only)'}")
    logger.info(f"  API keys: {len(settings.api_keys)} configured")
    logger.info(f"  Rate limit: {settings.rate_limit_rpm} req/min")
    logger.info(
        f"  Event log: {'enabled @ ' + str(settings.event_log_path) if settings.event_log_enabled else 'disabled'}"
    )
    logger.info(f"  Plugins: {', '.join(settings.plugin_modules)}")

    if settings._generated_key:
        logger.warning(
            "No API key configured — generated a temporary write key: %s",
            settings._generated_key,
        )
        logger.warning(
            "Set DECKHAND_API_KEY or add [auth] api_keys to your config file to persist a key."
        )

    # Initialize rate limiter
    rate_limiter = RateLimiter(settings.rate_limit_rpm)

    # Initialize orchestrator. Agents are registered on demand via the
    # Claude Code / Cursor hook handlers or POST /agents/register — no
    # framework-style default agents under the v0.3 positioning.
    orchestrator = Orchestrator(
        state_persist_path=settings.state_file_path,
        metrics=metrics,
    )

    # Initialize registries
    action_registry = ActionRegistry(
        orchestrator,
        metrics=metrics,
        event_bus=orchestrator.event_bus,
    )
    signal_registry = SignalRegistry(metrics=metrics)
    plugin_registry = PluginRegistry(
        actions=action_registry,
        signals=signal_registry,
        state=orchestrator.state_store,
        events=orchestrator.event_bus,
        orchestrator=orchestrator,
    )

    # Load plugins
    load_plugins(settings.plugin_specs, plugin_registry)
    logger.info(
        f"Loaded {len(action_registry.list_actions())} actions and {len(signal_registry.list_signals())} signals"
    )

    if settings.event_log_enabled:
        event_logger = EventLogger(settings.event_log_path)
        orchestrator.event_bus.add_listener(event_logger)
        logger.info("Event log writing to %s", event_logger.path)

    # Pending-input aggregator: maintains agents.pending_input{,_count}
    # state from agent.status_changed / agent.unregistered events.
    pending_tracker = PendingInputTracker(orchestrator.state_store)
    orchestrator.event_bus.add_listener(pending_tracker)

    logger.info("Deckhand service started")

    yield

    # Shutdown
    logger.info("Shutting down Deckhand service...")
    if plugin_registry is not None:
        await plugin_registry.run_shutdown_hooks()


app = FastAPI(title="Deckhand", version=SERVICE_VERSION, lifespan=lifespan)


# ---------------------------------------------------------------------------
# CORS middleware — locked to localhost origins
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Rate-limiting middleware
# ---------------------------------------------------------------------------


class _RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if rate_limiter is not None:
            client_ip = request.client.host if request.client else "unknown"
            if not rate_limiter.check(client_ip):
                logger.warning(
                    "Rate limit exceeded",
                    extra={"client_ip": client_ip, "path": request.url.path},
                )
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded"},
                )
        return await call_next(request)


app.add_middleware(_RateLimitMiddleware)


# ---------------------------------------------------------------------------
# Authentication & authorization helpers
# ---------------------------------------------------------------------------


def _extract_token(request: Request) -> str:
    """Extract Bearer token from the Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return auth_header


def _require_scope(request: Request, scope: str) -> ApiKeyEntry:
    """Validate API key and check it has at least *scope*."""
    if settings is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    client_ip = request.client.host if request.client else "unknown"
    log_ctx = {"client_ip": client_ip, "path": request.url.path, "scope": scope}

    token = _extract_token(request)
    if not token:
        logger.warning("Auth failed: missing API key", extra=log_ctx)
        raise HTTPException(status_code=401, detail="Missing API key")

    entry = resolve_key(token, settings.api_keys)
    if entry is None:
        logger.warning("Auth failed: invalid API key", extra=log_ctx)
        raise HTTPException(status_code=401, detail="Invalid API key")

    if not has_scope(entry, scope):
        logger.warning(
            "Auth failed: insufficient scope",
            extra={**log_ctx, "key_scope": entry.scope},
        )
        raise HTTPException(
            status_code=403, detail=f"Insufficient scope: requires '{scope}'"
        )

    return entry


async def require_read(request: Request) -> ApiKeyEntry:
    """Dependency: caller must hold at least 'read' scope."""
    return _require_scope(request, "read")


async def require_write(request: Request) -> ApiKeyEntry:
    """Dependency: caller must hold at least 'write' scope."""
    return _require_scope(request, "write")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class InputPayload(BaseModel):
    text: str


class ActionPayload(BaseModel):
    """Wrapper for action execution payloads."""

    payload: dict[str, object] = {}


class AgentRegisterPayload(BaseModel):
    """Payload for registering a new agent."""

    agent_id: str
    agent_type: str = "external"
    capabilities: list[str] = []
    project_root: str | None = None
    active_file: str | None = None


class AgentContextPayload(BaseModel):
    """Payload for updating an agent's project context."""

    project_root: str | None = None
    active_file: str | None = None


class ClaudeCodeHookPayload(BaseModel):
    """Payload pushed by a Claude Code hook (JSON piped to the hook command).

    Mirrors the schema Claude Code writes to hook stdin. Unknown fields are
    ignored so future hook additions do not break the endpoint.
    """

    session_id: str
    hook_event_name: str
    cwd: str | None = None
    transcript_path: str | None = None
    iterm_session_id: str | None = None


class CursorHookPayload(BaseModel):
    """Payload pushed by a Cursor IDE hook (JSON piped to the hook command)."""

    session_id: str
    hook_event_name: str
    cwd: str | None = None
    title: str | None = None
    deckhand_status: str | None = None


class SignalPayload(BaseModel):
    """Wrapper for signal webhook payloads."""

    payload: dict[str, object] = {}


# ---------------------------------------------------------------------------
# Health check (unauthenticated)
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, object]:
    """Service health check. Unauthenticated for monitoring/orchestration."""
    if (
        orchestrator is None
        or action_registry is None
        or signal_registry is None
        or settings is None
        or _service_start_time is None
    ):
        raise HTTPException(status_code=503, detail="Service not initialized")

    agents = orchestrator.list_agents()
    state_store = orchestrator.state_store

    return {
        "status": "ok",
        "version": SERVICE_VERSION,
        "uptime_seconds": time.time() - _service_start_time,
        "websocket_clients": orchestrator.event_bus.client_count,
        "agents": {
            "count": len(agents),
            "statuses": {a.id: a.status.value for a in agents},
        },
        "plugins": {
            "modules": list(settings.plugin_modules),
            "actions": len(action_registry.list_actions()),
            "signals": len(signal_registry.list_signals()),
        },
        "state_store": {
            "entry_count": state_store.entry_count(),
            "persist_path": state_store.persist_path,
            "writable": state_store.is_writable(),
        },
    }


# ---------------------------------------------------------------------------
# Metrics (unauthenticated)
# ---------------------------------------------------------------------------


@app.get("/metrics")
async def metrics_endpoint() -> dict[str, object]:
    """Operational metrics snapshot. Unauthenticated for monitoring."""
    if orchestrator is None or metrics is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    snapshot = metrics.snapshot()

    agents = list(orchestrator.list_agents())
    status_counts: dict[str, int] = {}
    for agent in agents:
        status = agent.status.value
        status_counts[status] = status_counts.get(status, 0) + 1

    snapshot["websocket_clients"] = orchestrator.event_bus.client_count
    snapshot["agents"] = {
        "count": len(agents),
        "by_status": status_counts,
    }
    snapshot["state_store"] = {
        "entry_count": orchestrator.state_store.entry_count(),
    }
    return snapshot


# ---------------------------------------------------------------------------
# Agent routes (read)
# ---------------------------------------------------------------------------


@app.get("/agents", dependencies=[Depends(require_read)])
async def list_agents() -> list[dict[str, object]]:
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return [agent.as_dict() for agent in orchestrator.list_agents()]


# ---------------------------------------------------------------------------
# Agent routes (write)
# ---------------------------------------------------------------------------


@app.post("/agents/{agent_id}/start", dependencies=[Depends(require_write)])
async def start_agent(agent_id: str) -> dict[str, str]:
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    try:
        await orchestrator.start_agent(agent_id)
    except KeyError as exc:
        await orchestrator.event_bus.emit(
            build_error_event(
                "NotFoundError",
                f"Agent not found: {agent_id}",
                {"kind": "api", "id": "agents.start"},
                {"agent_id": agent_id},
            )
        )
        raise HTTPException(status_code=404, detail="agent not found") from exc
    return {"status": "started"}


@app.post("/agents/{agent_id}/cancel", dependencies=[Depends(require_write)])
async def cancel_agent(agent_id: str) -> dict[str, str]:
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    try:
        await orchestrator.cancel_agent(agent_id)
    except KeyError as exc:
        await orchestrator.event_bus.emit(
            build_error_event(
                "NotFoundError",
                f"Agent not found: {agent_id}",
                {"kind": "api", "id": "agents.cancel"},
                {"agent_id": agent_id},
            )
        )
        raise HTTPException(status_code=404, detail="agent not found") from exc
    return {"status": "cancelled"}


@app.post("/agents/{agent_id}/input", dependencies=[Depends(require_write)])
async def provide_input(agent_id: str, payload: InputPayload) -> dict[str, str]:
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    try:
        await orchestrator.provide_input(agent_id, payload.text)
    except KeyError as exc:
        await orchestrator.event_bus.emit(
            build_error_event(
                "NotFoundError",
                f"Agent not found: {agent_id}",
                {"kind": "api", "id": "agents.input"},
                {"agent_id": agent_id},
            )
        )
        raise HTTPException(status_code=404, detail="agent not found") from exc
    return {"status": "input_sent"}


@app.post("/agents/register", dependencies=[Depends(require_write)])
async def register_agent(payload: AgentRegisterPayload) -> dict[str, object]:
    """Register a new external agent with optional project context."""
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    if orchestrator.get_agent(payload.agent_id) is not None:
        raise HTTPException(status_code=409, detail="agent already registered")

    from deckhand.agents.base import AgentBase, AgentStatus

    class ExternalAgent(AgentBase):
        """Placeholder agent for externally-managed processes."""

        async def start(self) -> None:
            await self._set_status(AgentStatus.RUNNING)

        async def cancel(self) -> None:
            await self._set_status(AgentStatus.IDLE)

        async def provide_input(self, text: str) -> None:
            pass

    agent = ExternalAgent(
        agent_id=payload.agent_id,
        agent_type=payload.agent_type,
        capabilities=payload.capabilities,
        project_root=payload.project_root,
        active_file=payload.active_file,
    )
    orchestrator.register_agent(agent)
    return agent.as_dict()


def _claude_code_agent_id(session_id: str) -> str:
    """Derive a stable agent id from a Claude Code session id."""
    short = session_id[:8] if len(session_id) >= 8 else session_id
    return f"claude-code-{short}"


@app.post("/agents/claude-code/hook", dependencies=[Depends(require_write)])
async def claude_code_hook(payload: ClaudeCodeHookPayload) -> dict[str, object]:
    """Receive a Claude Code hook event and reflect it onto a ClaudeCodeAgent.

    On first sighting of a ``session_id`` a new ClaudeCodeAgent is registered
    with the orchestrator using ``cwd`` as ``project_root``. Subsequent hook
    events update the agent's status. ``SessionEnd`` unregisters the agent.
    """
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    agent_id = _claude_code_agent_id(payload.session_id)
    existing = orchestrator.get_agent(agent_id)

    if payload.hook_event_name == "SessionEnd":
        if existing is not None:
            orchestrator.unregister_agent(agent_id)
            await orchestrator.event_bus.emit(
                build_event(
                    "agent.unregistered",
                    {"kind": "agent", "id": agent_id},
                    {"agent_id": agent_id, "reason": "session_end"},
                )
            )
        return {"status": "unregistered", "agent_id": agent_id}

    if existing is None:
        agent = ClaudeCodeAgent(
            agent_id=agent_id,
            session_id=payload.session_id,
            project_root=payload.cwd,
        )
        orchestrator.register_agent(agent)
        if payload.iterm_session_id:
            orchestrator.register_focuser(
                agent_id, make_iterm_focuser(payload.iterm_session_id)
            )
        await orchestrator.event_bus.emit(
            build_event(
                "agent.registered",
                {"kind": "agent", "id": agent_id},
                {"agent": agent.as_dict()},
            )
        )
    else:
        agent = existing  # type: ignore[assignment]
        if payload.cwd and agent.project_root != payload.cwd:
            agent.project_root = payload.cwd
        # Always (re)bind the focuser when iterm_session_id is present, so
        # late-arriving hook upgrades AND changes to the iTerm session id
        # (e.g. the user detached and reattached a session to a new tab)
        # take effect immediately. Building the closure is microsecond-cheap.
        if payload.iterm_session_id:
            orchestrator.register_focuser(
                agent_id, make_iterm_focuser(payload.iterm_session_id)
            )

    if not isinstance(agent, ClaudeCodeAgent):
        raise HTTPException(
            status_code=409,
            detail=f"agent id {agent_id} exists but is not a ClaudeCodeAgent",
        )

    await agent.apply_hook_event(payload.hook_event_name)
    return {"status": "ok", "agent": agent.as_dict()}


def _cursor_agent_id(session_id: str) -> str:
    """Derive a stable agent id from a Cursor session id."""
    short = session_id[:8] if len(session_id) >= 8 else session_id
    return f"cursor-{short}"


@app.post("/agents/cursor/hook", dependencies=[Depends(require_write)])
async def cursor_hook(payload: CursorHookPayload) -> dict[str, object]:
    """Receive a Cursor IDE hook event and reflect it onto a CursorAgent."""
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    agent_id = _cursor_agent_id(payload.session_id)
    existing = orchestrator.get_agent(agent_id)
    event_name = payload.hook_event_name

    if event_name == "sessionEnd":
        if existing is not None:
            orchestrator.unregister_agent(agent_id)
            await orchestrator.event_bus.emit(
                build_event(
                    "agent.unregistered",
                    {"kind": "agent", "id": agent_id},
                    {"agent_id": agent_id, "reason": "session_end"},
                )
            )
        await update_cursor_summary(orchestrator)
        return {"status": "unregistered", "agent_id": agent_id}

    if existing is None:
        agent = CursorAgent(
            agent_id=agent_id,
            session_id=payload.session_id,
            project_root=payload.cwd,
            title=payload.title,
        )
        orchestrator.register_agent(agent)
        orchestrator.register_focuser(agent_id, make_cursor_focuser(payload.cwd))
        await orchestrator.event_bus.emit(
            build_event(
                "agent.registered",
                {"kind": "agent", "id": agent_id},
                {"agent": agent.as_dict()},
            )
        )
    else:
        agent = existing  # type: ignore[assignment]
        if payload.cwd and agent.project_root != payload.cwd:
            agent.project_root = payload.cwd
            # Rebind the focuser so a workspace switch mid-session takes
            # effect on the next focus invocation. Building the closure is
            # microsecond-cheap; mirrors the late-binding pattern in the
            # Claude Code hook handler above.
            orchestrator.register_focuser(agent_id, make_cursor_focuser(payload.cwd))
        if payload.title and getattr(agent, "title", None) != payload.title:
            agent.title = payload.title  # type: ignore[attr-defined]

    if not isinstance(agent, CursorAgent):
        raise HTTPException(
            status_code=409,
            detail=f"agent id {agent_id} exists but is not a CursorAgent",
        )

    await agent.apply_hook_event(
        event_name,
        deckhand_status=payload.deckhand_status,
    )
    await update_cursor_summary(orchestrator)
    return {"status": "ok", "agent": agent.as_dict()}


@app.patch("/agents/{agent_id}/context", dependencies=[Depends(require_write)])
async def update_agent_context(
    agent_id: str, payload: AgentContextPayload
) -> dict[str, object]:
    """Update an agent's project context (project_root and/or active_file)."""
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    agent = orchestrator.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")

    if payload.project_root is not None:
        agent.project_root = payload.project_root
    if payload.active_file is not None:
        agent.active_file = payload.active_file

    await orchestrator.event_bus.emit(
        build_event(
            "agent.context_changed",
            {"kind": "agent", "id": agent_id},
            {"agent": agent.as_dict()},
        )
    )
    return agent.as_dict()


# ---------------------------------------------------------------------------
# Action routes
# ---------------------------------------------------------------------------


@app.post("/actions/{action_name}", dependencies=[Depends(require_write)])
async def run_action(
    action_name: str,
    payload: dict[str, object] = Body(default_factory=dict),
) -> dict[str, str]:
    if action_registry is None or orchestrator is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # Check action exists and validate payload against registered schema
    metadata = action_registry.get_action_metadata(action_name)
    if metadata is None:
        await orchestrator.event_bus.emit(
            build_error_event(
                "NotFoundError",
                f"Action not found: {action_name}",
                {"kind": "api", "id": "actions.run"},
                {"action_name": action_name},
            )
        )
        raise HTTPException(status_code=404, detail="action not found")

    errors = validate_payload(payload, metadata.payload_schema)
    if errors:
        await orchestrator.event_bus.emit(
            build_error_event(
                "ValidationError",
                f"Payload validation failed for action '{action_name}'",
                {"kind": "api", "id": "actions.run"},
                {"action_name": action_name, "errors": errors},
            )
        )
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    try:
        await action_registry.run(action_name, payload)
    except ValueError as exc:
        await orchestrator.event_bus.emit(
            build_error_event(
                "ValidationError",
                str(exc),
                {"kind": "api", "id": "actions.run"},
                {"action_name": action_name, "payload": payload},
            )
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok"}


@app.get("/actions", dependencies=[Depends(require_read)])
async def list_actions() -> dict[str, list[dict[str, object]]]:
    if action_registry is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    actions = action_registry.list_actions()
    return {
        "actions": [
            {
                "name": meta.name,
                "description": meta.description,
                "payload_schema": meta.payload_schema,
            }
            for meta in actions
        ]
    }


@app.get("/actions/{action_name}", dependencies=[Depends(require_read)])
async def get_action_metadata(action_name: str) -> dict[str, object]:
    if action_registry is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    metadata = action_registry.get_action_metadata(action_name)
    if metadata is None:
        raise HTTPException(status_code=404, detail="action not found")
    return {
        "name": metadata.name,
        "description": metadata.description,
        "payload_schema": metadata.payload_schema,
    }


# ---------------------------------------------------------------------------
# Signal routes
# ---------------------------------------------------------------------------


@app.post("/signals/webhook/{signal_name}", dependencies=[Depends(require_write)])
async def handle_webhook_signal(
    signal_name: str,
    payload: dict[str, object] = Body(default_factory=dict),
) -> dict[str, str]:
    if signal_registry is None or orchestrator is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # Check signal exists and validate payload against registered schema
    metadata = signal_registry.get_signal_metadata(signal_name)
    if metadata is None:
        await orchestrator.event_bus.emit(
            build_error_event(
                "NotFoundError",
                f"Signal not found: {signal_name}",
                {"kind": "api", "id": "signals.webhook"},
                {"signal_name": signal_name},
            )
        )
        raise HTTPException(status_code=404, detail="signal not found")

    errors = validate_payload(payload, metadata.payload_schema)
    if errors:
        await orchestrator.event_bus.emit(
            build_error_event(
                "ValidationError",
                f"Payload validation failed for signal '{signal_name}'",
                {"kind": "api", "id": "signals.webhook"},
                {"signal_name": signal_name, "errors": errors},
            )
        )
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    try:
        await signal_registry.handle(signal_name, payload)
    except ValueError as exc:
        await orchestrator.event_bus.emit(
            build_error_event(
                "ValidationError",
                str(exc),
                {"kind": "api", "id": "signals.webhook"},
                {"signal_name": signal_name, "payload": payload},
            )
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok"}


@app.get("/signals", dependencies=[Depends(require_read)])
async def list_signals() -> dict[str, list[dict[str, object]]]:
    if signal_registry is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    signals = signal_registry.list_signals()
    return {
        "signals": [
            {
                "name": meta.name,
                "description": meta.description,
                "payload_schema": meta.payload_schema,
            }
            for meta in signals
        ]
    }


@app.get("/signals/{signal_name}", dependencies=[Depends(require_read)])
async def get_signal_metadata(signal_name: str) -> dict[str, object]:
    if signal_registry is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    metadata = signal_registry.get_signal_metadata(signal_name)
    if metadata is None:
        raise HTTPException(status_code=404, detail="signal not found")
    return {
        "name": metadata.name,
        "description": metadata.description,
        "payload_schema": metadata.payload_schema,
    }


# ---------------------------------------------------------------------------
# State routes (read-only)
# ---------------------------------------------------------------------------


@app.get("/state", dependencies=[Depends(require_read)])
async def list_state() -> list[dict[str, object]]:
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return orchestrator.state_store.list_state()


@app.get("/state/{state_key}", dependencies=[Depends(require_read)])
async def get_state(state_key: str) -> dict[str, object]:
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    entry = orchestrator.state_store.get_state(state_key)
    if entry is None:
        raise HTTPException(status_code=404, detail="state not found")
    return entry


# ---------------------------------------------------------------------------
# WebSocket events — first-message auth handshake
# ---------------------------------------------------------------------------

_WS_AUTH_TIMEOUT = 5.0  # seconds to wait for auth message


@app.websocket("/events")
async def events(websocket: WebSocket) -> None:
    if orchestrator is None or settings is None:
        await websocket.close(code=1013, reason="Service not initialized")
        return

    # Accept the connection, then authenticate via first message
    await websocket.accept()
    client_ip = websocket.client.host if websocket.client else "unknown"
    ws_ctx = {"client_ip": client_ip, "path": "/events"}

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=_WS_AUTH_TIMEOUT)
        auth_msg = json.loads(raw)

        if auth_msg.get("type") != "auth" or "token" not in auth_msg:
            logger.warning("WS auth failed: malformed auth message", extra=ws_ctx)
            await websocket.send_json(
                {
                    "type": "auth_error",
                    "detail": "Expected {type: 'auth', token: '...'}",
                }
            )
            await websocket.close(code=4001, reason="Invalid auth message")
            return

        entry = resolve_key(auth_msg["token"], settings.api_keys)
        if entry is None:
            logger.warning("WS auth failed: invalid API key", extra=ws_ctx)
            await websocket.send_json(
                {"type": "auth_error", "detail": "Invalid API key"}
            )
            await websocket.close(code=4001, reason="Invalid API key")
            return

        await websocket.send_json({"type": "auth_ok", "scope": entry.scope})

    except asyncio.TimeoutError:
        logger.warning("WS auth failed: handshake timed out", extra=ws_ctx)
        await websocket.close(code=4001, reason="Auth handshake timed out")
        return
    except (json.JSONDecodeError, KeyError):
        logger.warning("WS auth failed: malformed auth message", extra=ws_ctx)
        await websocket.close(code=4001, reason="Malformed auth message")
        return

    # Authenticated — subscribe to event stream (already accepted, skip accept)
    await orchestrator.event_bus.subscribe(websocket, accept=False)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        orchestrator.event_bus.unsubscribe(websocket)
