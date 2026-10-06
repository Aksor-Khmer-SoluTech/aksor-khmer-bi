"""A small, strict JSONPath -- just enough to say where a value lives in an
API response, for a parameter's choice list (app/report_data.py's options
source): `$.data[*].code`, `data[0].name.en`, `result['nameEn']`.

Why not a library: a manager types these into a form and the server
evaluates them against whatever a remote API answered, so the language
should be one a reviewer can hold in their head -- no filter expressions
(`[?(@.a > 1)]`), no scripts, no recursive descent -- and errors should read
like a form hint, not a parser trace. What is accepted:

    $                    the root (a leading `$` is optional)
    .name  /  ['name']   an object's key         (also a bare leading `name`)
    [0]  /  [-1]         an array element, counted from the end when negative
    [*]  /  [ ]  /  .*   every element of an array (or value of an object)

`[]` is accepted as `[*]` because that is how people naturally write "each
item" (`data[].code`).

A field of a choice list can also be a template mixing text and paths in
`${...}` placeholders -- `${code} - ${nameEn}` -- for labels made of several
fields. A field with no `${` in it is one plain path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_PLACEHOLDER_RE = re.compile(r"\$\{([^{}]*)\}")
# A bare (dotted) key: anything that isn't structure. Khmer and hyphenated keys are fine.
_KEY_RE = re.compile(r"[^.\[\]\s'\"*$]+")


class JsonPathError(ValueError):
    """The path can't be parsed, or points at something that isn't one value.
    The message is written for whoever typed the path."""


@dataclass(frozen=True)
class Path:
    source: str
    # ("key", str) | ("index", int) | ("all",)
    steps: tuple[tuple, ...]

    @property
    def has_wildcard(self) -> bool:
        return any(step[0] == "all" for step in self.steps)

    def find(self, data: Any) -> list[Any]:
        """Every value the path reaches; a step that finds nothing simply
        contributes nothing (a missing key is not an error)."""
        nodes = [data]
        for step in self.steps:
            following: list[Any] = []
            for node in nodes:
                if step[0] == "key":
                    if isinstance(node, dict) and step[1] in node:
                        following.append(node[step[1]])
                elif step[0] == "index":
                    if isinstance(node, list) and -len(node) <= step[1] < len(node):
                        following.append(node[step[1]])
                else:
                    if isinstance(node, list):
                        following.extend(node)
                    elif isinstance(node, dict):
                        following.extend(node.values())
            nodes = following
        return nodes


def parse(source: str) -> Path:
    text = (source or "").strip()
    if not text:
        raise JsonPathError("The path is empty")
    pos = 0
    steps: list[tuple] = []

    if text.startswith("$"):
        pos = 1
    elif text[0] not in ".[":
        # `data[].code` / `code` -- a leading bare key, as if written `$.data[].code`.
        key = _KEY_RE.match(text)
        if key is None:
            raise JsonPathError(f"Can't read {source!r} as a path -- start with $ or a field name")
        steps.append(("key", key.group()))
        pos = key.end()

    while pos < len(text):
        char = text[pos]
        if char == ".":
            if text.startswith("..", pos):
                raise JsonPathError("'..' (search everywhere) isn't supported -- spell out the path, e.g. $.data[*].code")
            pos += 1
            if pos < len(text) and text[pos] == "*":
                steps.append(("all",))
                pos += 1
                continue
            key = _KEY_RE.match(text, pos)
            if key is None:
                raise JsonPathError(f"Expected a field name after '.' at position {pos + 1} of {source!r}")
            steps.append(("key", key.group()))
            pos = key.end()
        elif char == "[":
            close = _bracket_end(text, pos, source)
            inner = text[pos + 1 : close].strip()
            pos = close + 1
            steps.append(_bracket_step(inner, source))
        else:
            raise JsonPathError(f"Unexpected {char!r} at position {pos + 1} of {source!r}")
    return Path(text, tuple(steps))


def _bracket_end(text: str, start: int, source: str) -> int:
    """Index of the `]` closing the bracket at `start`, skipping over a quoted key."""
    pos = start + 1
    quote: str | None = None
    while pos < len(text):
        char = text[pos]
        if quote:
            if char == "\\":
                pos += 1
            elif char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "]":
            return pos
        pos += 1
    raise JsonPathError(f"Missing ']' in {source!r}")


def _bracket_step(inner: str, source: str) -> tuple:
    if inner in ("", "*"):
        return ("all",)
    if re.fullmatch(r"-?\d+", inner):
        return ("index", int(inner))
    if len(inner) >= 2 and inner[0] == inner[-1] and inner[0] in "'\"":
        return ("key", re.sub(r"\\(.)", r"\1", inner[1:-1]))
    if inner.startswith("?"):
        raise JsonPathError("Filters like [?(...)] aren't supported -- point at the array with [*] and let every item through")
    if ":" in inner or "," in inner:
        raise JsonPathError(f"Slices and unions ([{inner}]) aren't supported -- use [*], [0], or ['name']")
    raise JsonPathError(f"Can't read [{inner}] in {source!r} -- use [*], [0], or ['name']")


@dataclass(frozen=True)
class Expression:
    """One field of a choice list: a single path, or a template of `${path}`
    placeholders and literal text. Paths are relative to one item."""

    source: str
    # (literal, None) | (None, Path)
    parts: tuple[tuple[str | None, Path | None], ...]
    is_template: bool

    def evaluate(self, item: Any) -> str | None:
        """The text this field produces for `item`, or None when a value it
        needs isn't there (a missing key, or JSON null). Raises JsonPathError
        for a path that lands on an object or array -- that is never a
        sensible value, and printing it would only put JSON in a dropdown."""
        out: list[str] = []
        for literal, path in self.parts:
            if literal is not None:
                out.append(literal)
                continue
            found = path.find(item)
            if not found or found[0] is None:
                return None
            out.append(_scalar_text(found[0], path.source))
        return "".join(out)


def parse_expression(source: str, *, where: str = "field") -> Expression:
    """Parse a value/label field. A path that can match more than one thing
    (a wildcard) is refused: each item must yield one value, and the place for
    a wildcard is the items path."""
    text = (source or "").strip()
    if not text:
        raise JsonPathError(f"The {where} is empty")
    if "${" not in text:
        path = parse(text)
        _refuse_wildcard(path, where)
        return Expression(text, ((None, path),), False)

    parts: list[tuple[str | None, Path | None]] = []
    last = 0
    for match in _PLACEHOLDER_RE.finditer(text):
        if match.start() > last:
            parts.append((text[last : match.start()], None))
        path = parse(match.group(1))
        _refuse_wildcard(path, where)
        parts.append((None, path))
        last = match.end()
    if last < len(text):
        parts.append((text[last:], None))
    if "${" in "".join(literal or "" for literal, _ in parts):
        raise JsonPathError(f"Unclosed ${{ in the {where}: {text!r}")
    return Expression(text, tuple(parts), True)


def _refuse_wildcard(path: Path, where: str) -> None:
    if path.has_wildcard:
        raise JsonPathError(
            f"The {where} {path.source!r} matches many values -- each item needs exactly one, "
            "so pick one field (wildcards like [*] belong in the items path)"
        )


def _scalar_text(value: Any, path: str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise JsonPathError(f"{path!r} points at an object or a list, not a single value")


def find_items(path: Path | None, data: Any) -> list[Any]:
    """The list of items a choice list is built from. With no path, the
    response itself must be that list. With one, whatever it reaches: a path
    that lands on a single array (`$.data`) is that array; one that fans out
    (`$.data[*]`, `$.groups[*].items[*]`) is everything it reached."""
    if path is None:
        found = [data]
    else:
        found = path.find(data)
    if len(found) == 1 and isinstance(found[0], list):
        return found[0]
    if path is None:
        raise JsonPathError("The response isn't a JSON array -- set the items path to where the list is, e.g. $.data")
    if not found:
        return []
    return found
