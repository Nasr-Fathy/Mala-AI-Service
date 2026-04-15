from __future__ import annotations

import uuid
from typing import Any, Callable

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADER_NAME = b"x-request-id"


class RequestIDMiddleware:
    """
    Pure-ASGI middleware that propagates a request ID through every log line.

    Behaviour:
      1. If the caller sends an ``X-Request-ID`` header (e.g. the Django
         backend forwards its own request ID), the value is reused.
      2. Otherwise a UUID4 is generated.
      3. The ID is injected into ``structlog`` contextvars so every log
         message emitted while handling the request includes it.
      4. The ID is echoed back in the ``X-Request-ID`` response header so
         the caller can correlate the request with log output.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        request_id = _extract_request_id(scope) or str(uuid.uuid4())

        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            async def send_with_id(message: Message) -> None:
                if message["type"] == "http.response.start":
                    headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                    headers.append((HEADER_NAME, request_id.encode()))
                    message["headers"] = headers
                await send(message)

            await self.app(scope, receive, send_with_id)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")


def _extract_request_id(scope: Scope) -> str | None:
    for key, value in scope.get("headers", []):
        if key == HEADER_NAME:
            decoded = value.decode("latin-1").strip()
            if decoded:
                return decoded
    return None
