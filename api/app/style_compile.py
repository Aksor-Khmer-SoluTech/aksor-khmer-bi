"""Stylesheets in the formats people write them in -- CSS, SCSS, Sass (indented syntax) and Less -- turned into the CSS
an HTML template uses (the PDF engine, WeasyPrint, reads CSS only). stylesheet_store keeps the uploaded source beside
the compiled style.css, so the source can be edited and re-uploaded, and moves with a project.

The compilers: libsass for SCSS and Sass, lesscpy for Less. Their limits, said plainly where it matters:
* libsass is the older Sass engine: `@import` era Sass. The module system (`@use`, `@forward`, `sass:math`…) is not
  there; variables, nesting, mixins, functions, `@extend`, colour functions and maths are.
* lesscpy covers Less's common ground -- variables, nesting, mixins (with arguments and guards), operations, colour
  functions -- but not inline JavaScript or every built-in function.
* Stylus has no maintained compiler that runs here, so it isn't offered.

One file, self-contained: `@import`, `@use` and `@forward` are refused in SCSS/Sass/Less. Both compilers would
otherwise read the file named from the server's disk (an `@import "/etc/hosts"` compiles it into the output), and
there is no folder of partials to import from anyway -- put variables and mixins in the same file. (Plain CSS keeps
`@import url(...)`: it isn't followed at upload, and the renderer only ever loads `data:` URLs.)
"""
from __future__ import annotations

import io
import re

FORMATS = ("css", "scss", "sass", "less")
EXTENSIONS = {".css": "css", ".scss": "scss", ".sass": "sass", ".less": "less"}
LABELS = {"css": "CSS", "scss": "SCSS", "sass": "Sass", "less": "Less"}

_COMMENTS = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_IMPORTS = re.compile(r"(?m)^\s*@(import|use|forward)\b")


class StyleCompileError(ValueError):
    """The source doesn't compile -- the message says where (line, and what was expected)."""


def format_of(filename: str | None, declared: str | None = None) -> str:
    """The format of an upload: as declared, else from the file's extension; CSS when neither says."""
    if declared:
        if declared.lower() not in FORMATS:
            raise StyleCompileError(f"Unknown stylesheet format {declared!r} -- CSS, SCSS, Sass or Less")
        return declared.lower()
    name = (filename or "").lower()
    for ext, fmt in EXTENSIONS.items():
        if name.endswith(ext):
            return fmt
    if name.endswith((".styl", ".stylus")):
        raise StyleCompileError("Stylus isn't supported -- compile it to CSS first (stylus style.styl), then upload the .css")
    return "css"


def compile_style(source: bytes, fmt: str) -> bytes:
    """The CSS for `source` written in `fmt`. CSS is returned as it is."""
    if fmt == "css":
        return source
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StyleCompileError(f"Not valid UTF-8 text: {exc}") from exc
    found = _IMPORTS.search(_COMMENTS.sub("", text))
    if found:
        raise StyleCompileError(
            f"@{found.group(1)} isn't allowed in an uploaded {LABELS[fmt]} file -- it can't reach other files here. "
            "Put the variables and mixins it would bring in into this same file."
        )
    if fmt in ("scss", "sass"):
        return _sass(text, indented=fmt == "sass")
    return _less(text)


def _refuse_imports(path, prev=None):  # libsass importer: the second guard, should an import get past the check above
    raise StyleCompileError(f"@import {path!r} isn't allowed")


def _sass(text: str, *, indented: bool) -> bytes:
    import sass

    try:
        css = sass.compile(string=text, indented=indented, output_style="expanded", importers=[(0, _refuse_imports)], include_paths=[])
    except sass.CompileError as exc:
        raise StyleCompileError(_sass_message(str(exc))) from exc
    return css.encode("utf-8")


def _sass_message(raw: str) -> str:
    """libsass's message without its Python traceback: "Undefined variable: "$c". (line 3, column 12)"."""
    first = raw.strip().splitlines()[0].removeprefix("Error: ").strip() if raw.strip() else "It doesn't compile"
    where = re.search(r"on line (\d+):(\d+)", raw)
    if "isn't allowed" in raw or "Traceback" in first:
        return "@import isn't allowed in an uploaded file -- put everything in this one file"
    return f"{first} (line {where.group(1)}, column {where.group(2)})" if where else first


def _less(text: str) -> bytes:
    import lesscpy

    try:
        css = lesscpy.compile(io.StringIO(text), minify=False, xminify=False)
    except Exception as exc:  # noqa: BLE001 -- lesscpy raises many kinds (CompilationError, SyntaxError, ply errors)
        message = str(exc).strip() or type(exc).__name__
        message = re.sub(r"^E: line: 0:\s*", "", message)  # lesscpy's "line 0" means it doesn't know the line
        message = re.sub(r"^E: line: (\d+):\s*", r"line \1: ", message)
        raise StyleCompileError(f"It doesn't compile as Less: {message}") from exc
    return css.encode("utf-8")
