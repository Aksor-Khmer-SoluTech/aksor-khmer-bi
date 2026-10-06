"""Local-development convenience: fill the process environment from api/.env.

A bare `uvicorn app.main:app --reload` does not read api/.env -- only Docker Compose does --
so settings kept there (EMBED_TICKET_SECRET, PARTNER_API_KEY, LOG_LEVEL...)
silently stayed unset, and `--reload` never fixed that because a reloaded worker inherits the
launching shell's environment. Importing the `app` package now loads the file first, before any
module reads its settings, so a reload picks changes up too.

It only ever *fills gaps*: a variable that is already set (by the shell, Docker, CI) wins, so
this can't override a real deployment's configuration. And it does nothing where an .env file
is not meant to apply:

* inside a container (/.dockerenv, /run/.containerenv) -- those get their settings from the
  orchestrator, and a stray dev .env baked into an image must not change them;
* under pytest, so a developer's file can't leak into the test suite;
* when AKSOR_LOAD_DOTENV is 0/false/no.

Only variable *names* are ever reported (see `loaded()`); values are never logged.
"""
from __future__ import annotations

import os
import re
import sys
from collections.abc import MutableMapping
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / ".env"
ENV_SWITCH = "AKSOR_LOAD_DOTENV"

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_loaded: list[str] = []


def parse(text: str) -> dict[str, str]:
    """KEY=VALUE lines -> dict. Blank lines and `#` comments are skipped, `export ` is
    tolerated, a value may be wrapped in matching single or double quotes, and an unquoted
    value ends at a ` #` inline comment. No escape sequences or variable expansion."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, sep, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not sep or not _NAME_RE.match(name):
            continue
        if value[:1] in ('"', "'"):
            end = value.find(value[0], 1)
            value = value[1:end] if end != -1 else value[1:]
        else:
            value = re.split(r"\s#", value, maxsplit=1)[0].rstrip()
        values[name] = value
    return values


def load(path: Path = DEFAULT_PATH, environ: MutableMapping[str, str] | None = None) -> list[str]:
    """Set every variable in `path` that `environ` doesn't already have; return their names."""
    env = os.environ if environ is None else environ
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    filled = []
    for name, value in parse(text).items():
        if name not in env:
            env[name] = value
            filled.append(name)
    return filled


def _applies() -> bool:
    if os.environ.get(ENV_SWITCH, "").strip().lower() in {"0", "false", "no"}:
        return False
    if "pytest" in sys.modules:
        return False
    return not (Path("/.dockerenv").exists() or Path("/run/.containerenv").exists())


def autoload() -> None:
    global _loaded
    _loaded = load() if _applies() else []


def loaded() -> list[str]:
    """Names (never values) of the variables autoload() took from api/.env."""
    return list(_loaded)
