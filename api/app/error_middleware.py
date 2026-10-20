"""Give every request an id, and turn an unhandled server error into a JSON answer the browser can read.

**Request id.** Each request gets a short id: the one a reverse proxy already set in `X-Request-ID` (when it looks
like an id), else a new one. It is sent back in the `X-Request-ID` response header -- the portal shows it under an
error's "Technical details" -- and every log line written while the request runs carries it (`[req …]`, see
logging_config.RequestIdFilter). A failed request is logged once more with its method, path, status and time
taken, so the id a user reads out of the portal leads a technician straight to what happened.

**Unhandled errors.** Starlette puts its own error handler *outside* every middleware -- CORS included -- so a plain
500 leaves the server without the `Access-Control-Allow-Origin` header. A browser then reports "blocked by CORS
policy" and `TypeError: Failed to fetch`, hiding the real problem (a missing table, a bug) behind a misleading one.
This sits *inside* the CORS middleware, so the 500 it answers with carries the CORS headers and the portal can show
"the server hit an unexpected error" instead.

The message holds the request id as its reference, never the error's text (which can name tables, paths or hosts);
the same reference is in the server log next to the full traceback.
"""
from __future__ import annotations

import contextvars
import logging
import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_log = logging.getLogger("aksor_khmer_bi.errors")
_requests_log = logging.getLogger("aksor_khmer_bi.requests")

REQUEST_ID_HEADER = "X-Request-ID"
# A proxy's id is kept only when it is plainly an id: it ends up in logs and in a header we send back.
_INCOMING_ID = re.compile(r"^[A-Za-z0-9._-]{6,64}$")

# The id of the request being handled, for log records (empty outside a request).
current_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("current_request_id", default="")


def _request_id(scope: Scope) -> str:
    for name, value in scope.get("headers") or []:
        if name == b"x-request-id":
            incoming = value.decode("latin-1").strip()
            if _INCOMING_ID.match(incoming):
                return incoming
            break
    return uuid.uuid4().hex[:12]


class UnhandledErrorMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        reference = _request_id(scope)
        token = current_request_id.set(reference)
        started_at = time.monotonic()
        started = False
        status = 0

        async def tracking_send(message: Message) -> None:
            nonlocal started, status
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = reference
            await send(message)

        method, path = scope.get("method"), scope.get("path")
        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            _log.exception("Unhandled error on %s %s (ref %s)", method, path, reference)
            if started:  # a streamed response that already began can't be replaced
                raise
            response = JSONResponse(
                status_code=500,
                content={"detail": f"The server hit an unexpected error (ref {reference}) -- its log has the details"},
                headers={"Cache-Control": "no-store", REQUEST_ID_HEADER: reference},
            )
            await response(scope, receive, send)
        else:
            # A refused or failed request, once, with what a technician searches for. 401s are the routine
            # "access token expired, renew and retry" and would drown the rest.
            if status >= 400 and status != 401:
                level = logging.WARNING if status >= 500 else logging.INFO
                _requests_log.log(level, "%s %s -> %s in %dms", method, path, status, (time.monotonic() - started_at) * 1000)
        finally:
            current_request_id.reset(token)
