"""HTTP and WebSocket client wrapper used by the CLI."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Any, Self

import httpx

logger = logging.getLogger(__name__)


class DeckhandError(RuntimeError):
    """Raised when the service returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class DeckhandClient:
    """Thin synchronous wrapper over the Deckhand HTTP/WebSocket API."""

    def __init__(
        self,
        url: str,
        api_key: str | None,
        *,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._api_key = api_key
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            base_url=self._url,
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ HTTP

    def _request(self, method: str, path: str, *, json_body: Any | None = None) -> Any:
        try:
            response = self._client.request(method, path, json=json_body)
        except httpx.HTTPError as exc:
            raise DeckhandError(0, f"connection failed: {exc}") from exc
        if response.status_code >= 400:
            detail: str
            try:
                detail = response.json().get("detail", response.text)
            except (ValueError, TypeError, KeyError, AttributeError):
                detail = response.text
            raise DeckhandError(response.status_code, str(detail))
        if response.content:
            return response.json()
        return None

    # State
    def list_state(self) -> list[dict[str, Any]]:
        return self._request("GET", "/state") or []

    def get_state(self, key: str) -> dict[str, Any]:
        return self._request("GET", f"/state/{key}")

    # Actions
    def list_actions(self) -> list[dict[str, Any]]:
        return (self._request("GET", "/actions") or {}).get("actions", [])

    def call_action(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/actions/{name}", json_body=payload)

    # Signals
    def list_signals(self) -> list[dict[str, Any]]:
        return (self._request("GET", "/signals") or {}).get("signals", [])

    def fire_signal(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/signals/webhook/{name}", json_body=payload)

    # Agents
    def list_agents(self) -> list[dict[str, Any]]:
        return self._request("GET", "/agents") or []

    def start_agent(self, agent_id: str) -> dict[str, Any]:
        return self._request("POST", f"/agents/{agent_id}/start")

    def cancel_agent(self, agent_id: str) -> dict[str, Any]:
        return self._request("POST", f"/agents/{agent_id}/cancel")

    def agent_input(self, agent_id: str, text: str) -> dict[str, Any]:
        return self._request(
            "POST", f"/agents/{agent_id}/input", json_body={"text": text}
        )

    def register_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/agents/register", json_body=payload)

    def unregister_agent(self, agent_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/agents/{agent_id}")

    # Hooks
    def post_claude_code_hook(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/agents/claude-code/hook", json_body=payload)

    def post_cursor_hook(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/agents/cursor/hook", json_body=payload)

    # ------------------------------------------------------------------ WS

    @contextmanager
    def events(self) -> Iterator[Iterator[dict[str, Any]]]:
        """Yield an iterator of events from the WebSocket stream.

        Synchronous facade over an asyncio WebSocket connection. Use as::

            with client.events() as stream:
                for event in stream:
                    ...
        """
        loop = asyncio.new_event_loop()
        try:
            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

            async def runner() -> None:
                try:
                    async for evt in self._aevents():
                        await queue.put(evt)
                except Exception as exc:
                    logger.exception("WebSocket event stream failed")
                    await queue.put({"__error__": str(exc)})
                finally:
                    await queue.put(None)

            task = loop.create_task(runner())

            def iterator() -> Iterator[dict[str, Any]]:
                while True:
                    item = loop.run_until_complete(queue.get())
                    if item is None:
                        break
                    if "__error__" in item:
                        raise DeckhandError(0, item["__error__"])
                    yield item

            try:
                yield iterator()
            finally:
                task.cancel()
                try:
                    loop.run_until_complete(task)
                except asyncio.CancelledError:
                    pass
        finally:
            loop.close()

    async def _aevents(self) -> AsyncIterator[dict[str, Any]]:
        import websockets

        ws_url = (
            self._url.replace("http://", "ws://").replace("https://", "wss://")
            + "/events"
        )
        async with websockets.connect(ws_url) as ws:
            await ws.send(json.dumps({"type": "auth", "token": self._api_key or ""}))
            ack = json.loads(await ws.recv())
            if ack.get("type") != "auth_ok":
                raise DeckhandError(0, f"auth failed: {ack}")
            while True:
                raw = await ws.recv()
                yield json.loads(raw)
