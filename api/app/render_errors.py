"""What a person sees when a report fails to render.

A template that can't be rendered is almost always the template's author's
problem -- a loop that was never closed, a field the data doesn't have -- and
they find out by trying it. A bare "Internal Server Error" (or, worse, a
browser's "failed to fetch" because an unhandled error never got CORS headers)
tells them nothing. So a render failure is turned into a structured answer:

* **For someone who manages the report** (and so is testing it): what kind of
  failure, the engine's own message, the line it points at with the template
  text around it, a hint for the common mistakes, and the technical traceback.
* **For everyone else** (an end user running it, an embedded viewer, a public
  render call): a plain "it couldn't be generated, tell whoever manages it" and
  a reference. The same reference is in the server log next to the full
  traceback, so an administrator can find it from a screenshot.

Nothing here is secret -- it is the template's own text and the engine's
message -- but file paths and library internals are for managers only.
"""
from __future__ import annotations

import re
import sys
import sysconfig
import traceback
import uuid
from pathlib import Path
from typing import Any

import jinja2
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
_SITE = sysconfig.get_paths().get("purelib", "")
_MAX_TRACE = 9000

GENERIC = (
    "This report couldn't be generated. It's a problem with the report itself, not with what you entered -- "
    "tell whoever manages it"
)


class RenderError(HTTPException):
    """A report failed to render. `info` is the structured description sent alongside `detail`."""

    def __init__(self, status_code: int, detail: str, info: dict[str, Any]):
        super().__init__(status_code=status_code, detail=detail)
        self.info = info


async def render_error_handler(_: Request, exc: RenderError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "render_error": exc.info})


def _short_path(text: str) -> str:
    if _SITE:
        text = text.replace(_SITE, "<site-packages>")
    return text.replace(_REPO_ROOT, "<repo>")


def _trace_text(exc: BaseException) -> str:
    text = _short_path("".join(traceback.format_exception(exc)))
    return text if len(text) <= _MAX_TRACE else "…\n" + text[-_MAX_TRACE:]


def _in_template(exc: BaseException) -> bool:
    """The failure happened while Jinja was running the template itself (as opposed to the engine around it)."""
    return any(frame.filename in ("<template>", "<unknown>") for frame in traceback.extract_tb(exc.__traceback__))


_BLOCK_TAG = re.compile(r"\{%-?\s*(tr|tc|p)\s+[^%]*%\}")
_ANY_TAG = re.compile(r"\{%-?\s*(?:tr|tc|p|r)?\s*-?\s*(\w+)")


def _scan_template(template_path: Path | None) -> tuple[dict[str, int] | None, list[dict[str, Any]]]:
    """What the Word file holds, for diagnosing it: how many of each loop/condition tag there are (the
    quickest way to spot an unclosed or extra one), and every paragraph where a `{%p %}` / `{%tr %}` /
    `{%tc %}` tag shares its paragraph with anything else -- those tags *replace the paragraph they sit
    in*, so they must be alone."""
    if template_path is None or template_path.suffix.lower() != ".docx":
        return None, []
    try:
        import docx
        from docx.oxml.ns import qn

        document = docx.Document(str(template_path))
        parts: list[tuple[str, Any]] = [("the body", document.element.body)]
        for section in document.sections:
            for label, holder in (
                ("the header", section.header),
                ("the footer", section.footer),
                ("the first-page header", section.first_page_header),
                ("the first-page footer", section.first_page_footer),
            ):
                parts.append((label, holder._element))
        words: list[str] = []
        shared: list[dict[str, Any]] = []
        for label, part in parts:
            for number, paragraph in enumerate(part.iter(qn("w:p")), start=1):
                text = "".join(t.text or "" for t in paragraph.iter(qn("w:t")))
                words += _ANY_TAG.findall(text)
                blocks = _BLOCK_TAG.findall(text)
                if blocks:
                    alone = _BLOCK_TAG.sub("", text).strip() == "" and len(blocks) == 1
                    if not alone:
                        shared.append({"where": label, "paragraph": number, "text": " ".join(text.split())[:240]})
        return {tag: words.count(tag) for tag in ("for", "endfor", "if", "endif")}, shared
    except Exception:  # a diagnosis is never worth failing for
        return None, []


def _hint(exc: BaseException, counts: dict[str, int] | None, shared: list[dict[str, Any]] | None = None) -> str | None:
    message = str(getattr(exc, "message", None) or exc)
    if type(exc).__name__ == "ConversionError":
        if "could not be loaded" in message:
            return (
                "LibreOffice couldn't open the document generated from this template. Try re-saving the template from Word "
                "(a template saved by another tool, such as WPS Office, can carry quirks), or re-create it from a blank document; "
                "if even a simple template fails, LibreOffice itself isn't working on the server -- the log has its output."
            )
        return "The converter (LibreOffice) failed on the generated file. The log next to this reference has its full output."
    if shared and isinstance(exc, jinja2.TemplateSyntaxError):
        first = shared[0]
        return (
            f"A `{{%p …%}}` / `{{%tr …%}}` tag shares its paragraph with other text or tags ({first['where']}, paragraph {first['paragraph']}). "
            "Those tags replace the whole paragraph they sit in, so each one must be **alone in its own paragraph** -- "
            "one paragraph for `{%p for …%}`, one for what repeats, one for `{%p endfor %}`. "
            "To repeat words inside a single paragraph, use plain `{% for %}` … `{% endfor %}` instead."
        )
    if isinstance(exc, jinja2.TemplateSyntaxError):
        unknown = re.search(r"unknown tag '(\w+)'", message)
        if unknown and unknown.group(1) in ("endfor", "endif"):
            opener = "for" if unknown.group(1) == "endfor" else "if"
            found = ""
            if counts:
                found = f" This template has {counts[opener]} `{opener}` and {counts['end' + opener]} `end{opener}`."
            return (
                f"An `{unknown.group(1)}` has no matching `{opener}` before it.{found} Every `{{% {opener} %}}` needs exactly one "
                f"`{{% end{opener} %}}`, and in a table the tags go in their own marker rows: `{{%tr {opener} … %}}` and `{{%tr end{opener} %}}`, "
                "each alone in its row (outside a table, `{%p …%}` alone in its own paragraph)."
            )
        if "Unexpected end of template" in message or "expected token" in message and "end" in message:
            return (
                "A `{% for %}` or `{% if %}` was opened but never closed. Add the matching `{% endfor %}` / `{% endif %}`"
                + (
                    f" (this template has {counts['for']} `for` / {counts['endfor']} `endfor`, {counts['if']} `if` / {counts['endif']} `endif`)."
                    if counts
                    else "."
                )
            )
        if "expected token" in message or "unexpected" in message.lower():
            return "A `{{ … }}` or `{% … %}` is malformed -- look for a missing bracket, quote or `%}`, or a tag Word split with different formatting in the middle."
        return None
    if isinstance(exc, jinja2.UndefinedError):
        return (
            "The template uses a field the data doesn't have. Check the spelling against the keys your data source returns "
            "(a database query's rows are under `rows` unless you named them otherwise), or guard it with `{% if field is defined %}`."
        )
    if _in_template(exc) and isinstance(exc, TypeError):
        return "A value in the data isn't the kind the template expects here (for example looping over something that is empty or not a list)."
    return None


def _context_lines(exc: BaseException) -> list[dict[str, Any]] | None:
    """docxtpl attaches the template text around a syntax error (tags' XML stripped); show it with the failing line marked."""
    lineno = getattr(exc, "lineno", None)
    context = getattr(exc, "docx_context", None)
    if not lineno or context is None:
        return None
    lines = list(context)
    first = max(lineno - 4, 0) + 1
    return [{"line": first + i, "text": text.strip()[:300], "hit": first + i == lineno} for i, text in enumerate(lines)]


def build(exc: BaseException, *, template_path: Path | None, full: bool) -> RenderError:
    """The RenderError to raise for an unexpected failure while rendering. Logs the traceback either way."""
    reference = uuid.uuid4().hex[:8]
    template_problem = isinstance(exc, jinja2.TemplateError) or _in_template(exc)
    stage = "template" if template_problem else "render"
    info: dict[str, Any] = {"stage": stage, "reference": reference}

    if not full:
        return RenderError(422 if template_problem else 500, f"{GENERIC} (ref {reference})", info)

    counts, shared = _scan_template(template_path) if template_problem else (None, [])
    message = str(getattr(exc, "message", None) or exc) or type(exc).__name__
    info.update(
        {
            "type": type(exc).__name__,
            "message": message,
            "line": getattr(exc, "lineno", None),
            "hint": _hint(exc, counts, shared),
            "shared_tags": shared or None,
            "context": _context_lines(exc),
            "tag_counts": counts,
            "traceback": _trace_text(exc),
        }
    )
    summary = f"{'Template error' if template_problem else 'Rendering failed'}: {type(exc).__name__}: {message}"
    return RenderError(422 if template_problem else 500, summary, info)
