"""Turn an unhandled server error into a JSON answer the browser can read.

Starlette puts its own error handler *outside* every middleware -- CORS included -- so a plain 500 leaves
the server without the `Access-Control-Allow-Origin` header. A browser then reports "blocked by CORS policy" and
`TypeError: Failed to fetch`, hiding the real problem (a missing table, a bug) behind a misleading one. This sits
*inside* the CORS middleware, so the 500 it answers with carries the CORS headers and the portal can show
"the server hit an unexpected error" instead.

The message holds a reference only, never the error's text (which can name tables, paths or hosts); the same
reference is in the server log next to the full traceback.
"""
from __future__ import annotations

import logging
import uuid

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_log = logging.getLogger("aksor_khmer_bi.errors")


class UnhandledErrorMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            reference = uuid.uuid4().hex[:8]
            _log.exception("Unhandled error on %s %s (ref %s)", scope.get("method"), scope.get("path"), reference)
            if started:  # a streamed response that already began can't be replaced
                raise
            response = JSONResponse(
                status_code=500,
                content={"detail": f"The server hit an unexpected error (ref {reference}) -- its log has the details"},
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
