"""Parsing/validation for a user-uploaded HTML report template, and
resolving its `{{ resource('name') }}` references to real bytes at render
time -- the HTML-template counterpart to report_store.is_valid_office_file
(docx/xlsx) and context_media.py (image refs inside render *data*, not
inside the template file itself).

Kept in `api`, not doc_engine: doc_engine has no database/filesystem
access to the resource store (see context_media.py's module docstring for
the same reasoning) -- this module is the one seam where a template's
`resource(...)` *reference* becomes a real, callable `resource` value
Jinja2 can invoke while rendering, built from data only this layer can
reach (app/image_store.py, app/stylesheet_store.py).

Security note: an uploaded template is only reachable by a caller holding
`report:manage` (see routers/reports.py's module docstring), so this
isn't fully untrusted input -- but it's also not backend-authored, so two
independent layers stop it from reading local files or reaching internal
services via a crafted href/src:
  1. `parse_html_template` flags any literal href/src that isn't exactly
     one `{{ resource(...) }}` call as a registration-time error (see
     `_find_disallowed_references`) -- the *intended*, checked path.
  2. `weasyprint_engine.py` renders every user template through a
     WeasyPrint URLFetcher restricted to the `data:` scheme only, so even
     something layer 1 misses (e.g. a `url(...)` inside an uploaded
     stylesheet's own CSS) hits a hard render-time error instead of
     silently fetching a local file or an internal URL.
"""
from __future__ import annotations

import re
from base64 import b64encode
from dataclasses import dataclass, field

from jinja2 import Environment, TemplateSyntaxError, meta, nodes

from . import image_store, stylesheet_store

# The context key `resource` is bound under before a template_ext="html"
# report reaches doc_engine.render() (see routers/reports.py's
# _render_one) -- reserved: no uploaded template can have a "real"
# top-level field collide with it, since Jinja resolves it from **context
# regardless of whether ParsedHtmlTemplate.fields also lists it (it never
# will -- find_undeclared_variables sees it as declared-by-caller, and it
# never appears there since it's a function, not `{{ resource }}` on its
# own).
RESOURCE_CONTEXT_KEY = "resource"

_env = Environment()

_HREF_SRC_RE = re.compile(r'\b(?:href|src)\s*=\s*(["\'])(.*?)\1', re.IGNORECASE | re.DOTALL)
_RESOURCE_CALL_ONLY_RE = re.compile(r"""^\s*\{\{\s*resource\(\s*['"][^'"]+['"]\s*\)\s*\}\}\s*$""")


@dataclass
class TemplateIssue:
    message: str
    line: int | None = None
    column: int | None = None


@dataclass
class ParsedHtmlTemplate:
    fields: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    errors: list[TemplateIssue] = field(default_factory=list)


def parse_html_template(source: str) -> ParsedHtmlTemplate:
    """Best-effort static analysis of an uploaded HTML template's Jinja2
    source -- same "cheap sanity check" spirit as
    report_store.is_valid_office_file, just a real AST parse instead of a
    zip-entry check (HTML has no equivalent structural giveaway to sniff).

    Any returned `errors` should block registration (see
    routers/reports.py's create_report) -- a syntax error means the AST
    couldn't be built at all, so `fields`/`resources` come back empty in
    that case (there was nothing to walk).
    """
    try:
        ast = _env.parse(source)
    except TemplateSyntaxError as exc:
        return ParsedHtmlTemplate(errors=[TemplateIssue(message=exc.message or str(exc), line=exc.lineno)])

    fields = sorted(meta.find_undeclared_variables(ast) - {RESOURCE_CONTEXT_KEY})
    resources = sorted(_find_resource_names(ast))
    errors = [
        TemplateIssue(message=f"href/src must use {{{{ resource('name') }}}}, not a direct URL: {ref!r}")
        for ref in _find_disallowed_references(source)
    ]
    return ParsedHtmlTemplate(fields=fields, resources=resources, errors=errors)


def _find_resource_names(ast: nodes.Template) -> set[str]:
    """Walk the AST for `resource('literal-name')` calls. Only literal
    string arguments are caught (`resource(some_variable)` can't be
    resolved without actually rendering) -- same best-effort caveat as
    get_report_schema's docx/xlsx field detection.
    """
    names: set[str] = set()
    for call in ast.find_all(nodes.Call):
        target = call.node
        if isinstance(target, nodes.Name) and target.name == RESOURCE_CONTEXT_KEY:
            if call.args and isinstance(call.args[0], nodes.Const) and isinstance(call.args[0].value, str):
                names.add(call.args[0].value)
    return names


def _find_disallowed_references(source: str) -> list[str]:
    """Every `href=`/`src=` in the raw uploaded source must be exactly
    one `{{ resource('name') }}` call (whitespace aside), a same-page
    `#anchor`, or empty -- anything else (a plain relative path, an
    absolute `http(s)://`/`file://` URL, a resource() call mixed with
    other text) is flagged so the register dialog can explain why, rather
    than the reference silently 404ing or being blocked at render time.
    """
    disallowed = []
    for match in _HREF_SRC_RE.finditer(source):
        value = match.group(2).strip()
        if not value or value.startswith("#"):
            continue
        if _RESOURCE_CALL_ONLY_RE.match(value):
            continue
        disallowed.append(value)
    return disallowed


class ResourceBindingError(ValueError):
    """Raised when a template's resource_bindings are missing an entry
    for a reference the template actually makes, or an entry points at a
    resource that doesn't exist / belongs to a different org than the
    report being registered or rendered.
    """


def validate_resource_bindings(resource_names: set[str], bindings: dict[str, dict], org_id: str) -> list[str]:
    """Authoritative check run at register time (routers/reports.py's
    create_report) -- returns human-readable error strings, empty means
    valid. The register dialog also calls POST /reports/parse-template
    first and won't normally let a caller submit past this, but the
    server re-checks rather than trusting the client's own bookkeeping.
    """
    errors: list[str] = []
    for name in sorted(resource_names):
        binding = bindings.get(name)
        if binding is None:
            errors.append(f"No resource mapped for {name!r}")
            continue
        errors.extend(_check_binding_exists(name, binding, org_id))
    return errors


def _check_binding_exists(name: str, binding: dict, org_id: str) -> list[str]:
    kind = binding.get("kind")
    resource_id = binding.get("id")
    if kind == "image":
        try:
            meta = image_store.get_image(resource_id)
        except image_store.ImageNotFoundError:
            return [f"{name!r} maps to an image that no longer exists"]
        if meta["org_id"] != org_id:
            return [f"{name!r} maps to an image from a different organization"]
        return []
    if kind == "stylesheet":
        try:
            meta = stylesheet_store.get_stylesheet(resource_id)
        except stylesheet_store.StylesheetNotFoundError:
            return [f"{name!r} maps to a stylesheet that no longer exists"]
        if meta["org_id"] != org_id:
            return [f"{name!r} maps to a stylesheet from a different organization"]
        return []
    return [f"{name!r} has an unrecognized resource kind {kind!r}"]


def build_resource_resolver(bindings: dict[str, dict] | None, org_id: str | None):
    """Returns the callable bound into a render context under
    RESOURCE_CONTEXT_KEY (see routers/reports.py's _render_one) so
    `{{ resource('logo.png') }}` resolves to a self-contained `data:` URI
    -- WeasyPrint never needs to fetch a real file path or URL for
    anything a template author referenced through the sanctioned path.
    """
    bindings = bindings or {}

    def _resolve(name: str) -> str:
        binding = bindings.get(name)
        if binding is None:
            raise ResourceBindingError(f"Template references resource {name!r} with no mapping")
        kind = binding.get("kind")
        resource_id = binding.get("id")
        if kind == "image":
            try:
                meta = image_store.get_image(resource_id)
                content = image_store.get_image_bytes(resource_id)
            except image_store.ImageNotFoundError:
                raise ResourceBindingError(f"Image mapped to {name!r} no longer exists")
            content_type = meta["content_type"]
        elif kind == "stylesheet":
            try:
                meta = stylesheet_store.get_stylesheet(resource_id)
                content = stylesheet_store.get_stylesheet_bytes(resource_id)
            except stylesheet_store.StylesheetNotFoundError:
                raise ResourceBindingError(f"Stylesheet mapped to {name!r} no longer exists")
            content_type = "text/css"
        else:
            raise ResourceBindingError(f"Resource {name!r} has an unrecognized kind {kind!r}")
        if org_id is None or meta["org_id"] != org_id:
            raise ResourceBindingError(f"Resource mapped to {name!r} does not belong to this report's organization")
        return f"data:{content_type};base64,{b64encode(content).decode('ascii')}"

    return _resolve
