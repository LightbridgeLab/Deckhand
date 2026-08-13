"""Lightweight async client for the Deckhand Core HTTP + WebSocket API."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

import aiohttp

logger = logging.getLogger("deckhand-bridge")

RefreshConnection = Callable[[], tuple[str, str | None]]

# Reconnection parameters
_RECONNECT_BASE_DELAY = 1.0  # seconds
_RECONNECT_MAX_DELAY = 30.0  # seconds
_RECONNECT_BACKOFF = 2.0  # multiplier


class DeckhandBridge:
    """Talks to Deckhand Core over HTTP (actions/state) and WebSocket (events)."""

    def __init__(
        self, base_url: str = "http://localhost:18765", api_key: str | None = None
    ) -> None:
        # WebSocket URL no longer carries the token as a query param;
        # authentication happens via a first-message handshake instead.
        self._set_urls(base_url)
        self._api_key = api_key
        self._session: aiohttp.ClientSession | None = None
        self.connected = False

    def _set_urls(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        ws_base = self.base_url.replace("http://", "ws://").replace(
            "https://", "wss://"
        )
        self.ws_url = f"{ws_base}/events"

    async def apply_connection(self, base_url: str, api_key: str | None) -> None:
        """Point the bridge at a (possibly new) Core URL / key."""
        new_url = base_url.rstrip("/")
        if new_url == self.base_url and api_key == self._api_key:
            return
        await self.close()
        self._set_urls(new_url)
        self._api_key = api_key
        logger.info("Deckhand Core URL updated to %s", self.base_url)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers: dict[str, str] = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._session = aiohttp.ClientSession(headers=headers)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ----- HTTP: Agents -----

    async def list_agents(self) -> list[dict[str, Any]]:
        session = await self._get_session()
        async with session.get(f"{self.base_url}/agents") as resp:
            resp.raise_for_status()
            return await resp.json()

    async def start_agent(self, agent_id: str) -> None:
        session = await self._get_session()
        async with session.post(f"{self.base_url}/agents/{agent_id}/start") as resp:
            resp.raise_for_status()

    async def cancel_agent(self, agent_id: str) -> None:
        session = await self._get_session()
        async with session.post(f"{self.base_url}/agents/{agent_id}/cancel") as resp:
            resp.raise_for_status()

    async def provide_input(self, agent_id: str, text: str) -> None:
        session = await self._get_session()
        async with session.post(
            f"{self.base_url}/agents/{agent_id}/input",
            json={"text": text},
        ) as resp:
            resp.raise_for_status()

    async def register_agent(
        self,
        agent_id: str,
        agent_type: str = "external",
        capabilities: list[str] | None = None,
        project_root: str | None = None,
        active_file: str | None = None,
    ) -> dict[str, Any]:
        session = await self._get_session()
        body: dict[str, Any] = {
            "agent_id": agent_id,
            "agent_type": agent_type,
            "capabilities": capabilities or [],
        }
        if project_root is not None:
            body["project_root"] = project_root
        if active_file is not None:
            body["active_file"] = active_file
        async with session.post(f"{self.base_url}/agents/register", json=body) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def update_agent_context(
        self,
        agent_id: str,
        project_root: str | None = None,
        active_file: str | None = None,
    ) -> dict[str, Any]:
        session = await self._get_session()
        body: dict[str, Any] = {}
        if project_root is not None:
            body["project_root"] = project_root
        if active_file is not None:
            body["active_file"] = active_file
        async with session.patch(
            f"{self.base_url}/agents/{agent_id}/context", json=body
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ----- HTTP: Actions -----

    async def list_actions(self) -> list[dict[str, Any]]:
        """Fetch registered actions from Core (``GET /actions``)."""
        session = await self._get_session()
        async with session.get(f"{self.base_url}/actions") as resp:
            resp.raise_for_status()
            data = await resp.json()
        actions = data.get("actions", []) if isinstance(data, dict) else []
        return actions if isinstance(actions, list) else []

    async def execute_action(
        self, action_name: str, payload: dict[str, Any] | None = None
    ) -> None:
        session = await self._get_session()
        async with session.post(
            f"{self.base_url}/actions/{action_name}",
            json=payload or {},
        ) as resp:
            resp.raise_for_status()

    # ----- HTTP: Signals -----

    async def send_signal(
        self, signal_name: str, payload: dict[str, Any] | None = None
    ) -> None:
        session = await self._get_session()
        async with session.post(
            f"{self.base_url}/signals/webhook/{signal_name}",
            json=payload or {},
        ) as resp:
            resp.raise_for_status()

    # ----- HTTP: State -----

    async def get_state(self, key: str) -> dict[str, Any] | None:
        session = await self._get_session()
        async with session.get(f"{self.base_url}/state/{key}") as resp:
            if resp.status == 404:
                return None
            resp.raise_for_status()
            return await resp.json()

    async def list_state(self) -> list[dict[str, Any]]:
        session = await self._get_session()
        async with session.get(f"{self.base_url}/state") as resp:
            resp.raise_for_status()
            return await resp.json()

    async def list_state_key_catalog(self) -> dict[str, Any]:
        """Fetch ``[catalog.state_keys]`` from Core (``GET /catalog/state_keys``)."""
        session = await self._get_session()
        async with session.get(f"{self.base_url}/catalog/state_keys") as resp:
            resp.raise_for_status()
            return await resp.json()

    # ----- WebSocket: Events (first-message auth + reconnection) -----

    async def subscribe_events(
        self,
        callback: Callable[[dict[str, Any]], Any],
        refresh: RefreshConnection | None = None,
    ) -> None:
        """Connect to Deckhand Core's event stream with automatic reconnection.

        Authenticates via a first-message handshake (sends ``{type: "auth",
        token: "..."}`` and waits for ``{type: "auth_ok"}``) instead of passing
        the token as a query parameter.

        Uses exponential backoff when the connection drops.
        Runs indefinitely until cancelled.
        """
        delay = _RECONNECT_BASE_DELAY

        while True:
            try:
                if refresh is not None:
                    url, key = refresh()
                    await self.apply_connection(url, key)
                session = await self._get_session()
                async with session.ws_connect(self.ws_url) as ws:
                    # --- first-message auth handshake ---
                    if self._api_key:
                        await ws.send_json({"type": "auth", "token": self._api_key})
                        auth_resp = await ws.receive_json()
                        if auth_resp.get("type") != "auth_ok":
                            detail = auth_resp.get("detail", "unknown error")
                            logger.error("WebSocket auth failed: %s", detail)
                            raise ConnectionError(f"Auth handshake failed: {detail}")

                    self.connected = True
                    delay = _RECONNECT_BASE_DELAY  # Reset on successful connect
                    logger.info("Connected to Deckhand Core event stream")

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                event = json.loads(msg.data)
                                result = callback(event)
                                if asyncio.iscoroutine(result):
                                    await result
                            except json.JSONDecodeError:
                                logger.warning(
                                    "Invalid JSON from Deckhand Core: %s", msg.data
                                )
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break

            except asyncio.CancelledError:
                self.connected = False
                raise
            except Exception:
                self.connected = False
                logger.warning(
                    "Deckhand Core WebSocket disconnected, reconnecting in %.1fs",
                    delay,
                    exc_info=True,
                )
                await asyncio.sleep(delay)
                delay = min(delay * _RECONNECT_BACKOFF, _RECONNECT_MAX_DELAY)
