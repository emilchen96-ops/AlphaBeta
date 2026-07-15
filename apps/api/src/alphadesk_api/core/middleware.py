"""HTTP correlation and structured request logging middleware."""

import logging
import re
import time
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from alphadesk_api.core.logging import reset_correlation_id, set_correlation_id

LOGGER = logging.getLogger(__name__)
CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def normalize_correlation_id(value: str | None) -> str:
    """Accept a bounded safe identifier or generate a UUID."""

    if value is not None and CORRELATION_ID_PATTERN.fullmatch(value):
        return value
    return str(uuid4())


class CorrelationIdMiddleware:
    """Attach a correlation ID to request state, response headers, and logs."""

    def __init__(self, app: ASGIApp, *, header_name: str) -> None:
        self.app = app
        self.header_name = header_name
        self.header_bytes = header_name.lower().encode("latin-1")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = None
        for name, value in scope.get("headers", []):
            if name.lower() == self.header_bytes:
                incoming = value.decode("latin-1")
                break

        correlation_id = normalize_correlation_id(incoming)
        scope.setdefault("state", {})["correlation_id"] = correlation_id
        token = set_correlation_id(correlation_id)
        started = time.perf_counter()
        status_code = 500

        async def send_with_correlation(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((self.header_bytes, correlation_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_correlation)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            path = scope.get("path", "")
            level = (
                logging.DEBUG if path.startswith("/health/") and status_code < 500 else logging.INFO
            )
            if status_code >= 500:
                level = logging.ERROR
            LOGGER.log(
                level,
                "HTTP request completed",
                extra={
                    "correlation_id": correlation_id,
                    "request_method": scope.get("method"),
                    "request_path": path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            reset_correlation_id(token)
