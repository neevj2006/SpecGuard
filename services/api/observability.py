"""Bounded request metrics and logs without source text or raw request paths."""

import json
import logging
import threading
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("specguard.requests")
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


class RequestMetrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str, int], dict] = {}

    def record(self, method: str, route: str, status: int, duration: float, failed: bool):
        with self._lock:
            key = (method, route, status // 100)
            if key not in self._rows and len(self._rows) >= 200:
                key = ("OTHER", "<overflow>", 0)
            row = self._rows.setdefault(
                key, {"requests": 0, "errors": 0, "total_ms": 0.0, "max_ms": 0.0}
            )
            row["requests"] += 1
            row["errors"] += int(failed or status >= 500)
            row["total_ms"] += duration
            row["max_ms"] = max(row["max_ms"], duration)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "scope": "process",
                "routes": [
                    {
                        "method": method,
                        "route": route,
                        "status_class": status,
                        "requests": row["requests"],
                        "errors": row["errors"],
                        "mean_ms": round(row["total_ms"] / row["requests"], 3),
                        "max_ms": round(row["max_ms"], 3),
                    }
                    for (method, route, status), row in sorted(self._rows.items())
                ],
            }


class RequestObservability:
    def __init__(self, app: ASGIApp, metrics: RequestMetrics):
        self.app, self.metrics = app, metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        identifier = uuid.uuid4().hex
        started, status, failed = time.perf_counter(), 500, False

        async def response(message: Message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"x-request-id"
                ]
                message = {**message, "headers": [*headers, (b"x-request-id", identifier.encode())]}
            await send(message)

        try:
            await self.app(scope, receive, response)
        except BaseException:
            failed = True
            raise
        finally:
            duration = (time.perf_counter() - started) * 1000
            method = scope.get("method", "OTHER")
            method = method if method in METHODS else "OTHER"
            route = getattr(scope.get("route"), "path", "<unmatched>")
            self.metrics.record(method, route, status, duration, failed)
            logger.info(
                json.dumps(
                    {
                        "event": "request_completed",
                        "request_id": identifier,
                        "method": method,
                        "route": route,
                        "status": status,
                        "duration_ms": round(duration, 3),
                        "failed": failed,
                    }
                )
            )
