"""Central logging setup, shared by the `api` process (uvicorn) and the
standalone `scheduler` entrypoint (app/scheduler.py's `main()`).

Uvicorn only configures its own "uvicorn" / "uvicorn.error" /
"uvicorn.access" loggers -- it never touches the root logger. Without this,
every `logging.getLogger("aksor_khmer_bi.*")` call in the app (auth.py,
auth_ldap.py, celery_app.py, scheduler.py, ...) propagates to an
unconfigured root logger: INFO/DEBUG records are silently dropped, and
WARNING/ERROR ones (including `_log.exception(...)` tracebacks) only print
through Python's bare "handler of last resort" -- no timestamp, no logger
name.

`LOG_LEVEL` picks the level for both this app's own loggers and
third-party ones (sqlalchemy, ldap3, ...). Every process also gets a
rotating file handler (see `DailySizeRotatingFileHandler` below) on top of
the console one, writing under `LOG_DIR`. See docs/deployment.md.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

_LEVEL_ALIASES = {"WARN": "WARNING"}
_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

_DEFAULT_LOG_DIR = "logs"
_DEFAULT_MAX_BYTES = 25 * 1024 * 1024  # 25MB

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


class DailySizeRotatingFileHandler(logging.Handler):
    """Writes to `<directory>/<prefix>-<YYYY-MM-DD>.log`.

    Once the current file would exceed `max_bytes`, rolls over to
    `<prefix>-<YYYY-MM-DD>.1.log`, then `.2.log`, etc. -- still the same
    date, just the next sequence number. The first record written after
    the calendar date changes (process kept running past midnight) starts
    a fresh `<prefix>-<new-date>.log` at sequence 0, regardless of the
    previous file's size.

    Not safe for two processes sharing one `(directory, prefix)` pair --
    each process tracks its own size/sequence in memory, so pick a prefix
    unique per process (configure_logging()'s `service` argument).
    """

    def __init__(self, directory: str, prefix: str, max_bytes: int, encoding: str = "utf-8") -> None:
        super().__init__()
        self._directory = directory
        self._prefix = prefix
        self._max_bytes = max_bytes
        self._encoding = encoding
        os.makedirs(directory, exist_ok=True)
        self._date = self._today()
        self._seq = self._latest_existing_seq(self._date)
        self._size = 0
        self._stream = self._open(self._date, self._seq)

    @staticmethod
    def _today() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _path(self, date: str, seq: int) -> str:
        name = f"{self._prefix}-{date}.log" if seq == 0 else f"{self._prefix}-{date}.{seq}.log"
        return os.path.join(self._directory, name)

    def _latest_existing_seq(self, date: str) -> int:
        """Resume mid-sequence on restart instead of overwriting today's
        newest file from scratch."""
        seq = 0
        while os.path.exists(self._path(date, seq + 1)):
            seq += 1
        return seq

    def _open(self, date: str, seq: int):
        path = self._path(date, seq)
        self._size = os.path.getsize(path) if os.path.exists(path) else 0
        return open(path, "a", encoding=self._encoding)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            today = self._today()
            if today != self._date:
                self._stream.close()
                self._date, self._seq = today, 0
                self._stream = self._open(self._date, self._seq)

            msg = self.format(record) + "\n"
            encoded_len = len(msg.encode(self._encoding, errors="replace"))
            if self._size and self._size + encoded_len > self._max_bytes:
                self._stream.close()
                self._seq += 1
                self._stream = self._open(self._date, self._seq)

            self._stream.write(msg)
            self._stream.flush()
            self._size += encoded_len
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        try:
            self._stream.close()
        finally:
            super().close()


def configure_logging(service: str = "app") -> None:
    # Mirrors logging.basicConfig()'s own "no-op if the root logger is
    # already configured" rule -- checked here too, and first, so a
    # second call (or a test run where pytest's own logging plugin got
    # there first) doesn't open a log file just to leave it unused.
    if logging.getLogger().handlers:
        return

    raw = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    raw = _LEVEL_ALIASES.get(raw, raw)
    level = raw if raw in _VALID_LEVELS else "INFO"

    formatter = logging.Formatter(_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    log_dir = os.environ.get("LOG_DIR", _DEFAULT_LOG_DIR)
    max_bytes = int(os.environ.get("LOG_MAX_BYTES", _DEFAULT_MAX_BYTES))
    file_handler = DailySizeRotatingFileHandler(log_dir, prefix=service, max_bytes=max_bytes)
    file_handler.setFormatter(formatter)

    logging.basicConfig(level=level, handlers=[console_handler, file_handler])

    # sqlalchemy/log.py pins the "sqlalchemy" logger to WARNING at import
    # time (if it's still NOTSET), which silently shadows LOG_LEVEL above
    # for SQL statement logging regardless of import order. Set
    # "sqlalchemy.engine"'s own level directly so it isn't affected by that
    # parent-logger pin: INFO logs each statement + its bound parameters,
    # DEBUG additionally logs fetched result rows.
    logging.getLogger("sqlalchemy.engine").setLevel(level)
