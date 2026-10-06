"""Validating a report's own protected-terms config (a `set_ids` list of
ProtectedTermSet references plus its own local terms/exclude_terms --
app/models/protected_terms.py's ProtectedTermsConfig) and resolving it
into the two flat lists app/routers/reports.py's `_render_one` needs.

See specs/protected_terms_design.md for the full design -- in short:
this is a second, per-report layer on top of aksor_khmer_ocr_segmenter's
own deployment-wide default (built-ins + the four
AKSOR_KHMER_OCR_PROTECTED_TERMS_*/EXCLUDED_TERMS_* env vars), fed into
that same package's `_sorted_terms` merge via the `extra_terms`/
`exclude_terms` kwargs threaded through doc_engine.render(). Nothing
here touches or knows about that deployment-wide floor.
"""
from __future__ import annotations

import logging

from . import protected_term_sets_store

_log = logging.getLogger("aksor_khmer_bi.protected_terms_config")

MAX_SET_IDS = 20
MAX_TERMS = 1000
MAX_TERM_LENGTH = 200
MAX_NAME_LENGTH = 200


class ProtectedTermsConfigError(ValueError):
    """The manager-supplied config is invalid (-> 400)."""


# --- validating what a manager saves -----------------------------------


def _clean_term_list(raw: list[str], where: str) -> list[str]:
    if len(raw) > MAX_TERMS:
        raise ProtectedTermsConfigError(f"{where} has too many terms (max {MAX_TERMS})")
    cleaned: list[str] = []
    seen: set[str] = set()
    for term in raw:
        value = (term or "").strip()
        if not value:
            continue  # blank entries are silently dropped, not an error -- easy to leave a stray blank line
        if len(value) > MAX_TERM_LENGTH:
            raise ProtectedTermsConfigError(f"A term in {where} is too long (max {MAX_TERM_LENGTH} characters)")
        if value in seen:
            continue  # duplicates collapse silently, same as segmenter._sorted_terms's own dedup
        seen.add(value)
        cleaned.append(value)
    return cleaned


def validate_term_set_fields(name: str, description: str | None, terms: list[str], exclude_terms: list[str]) -> dict:
    """Shared by create/update of a ProtectedTermSet itself."""
    name = (name or "").strip()
    if not name:
        raise ProtectedTermsConfigError("A protected term set needs a name")
    if len(name) > MAX_NAME_LENGTH:
        raise ProtectedTermsConfigError(f"The name is too long (max {MAX_NAME_LENGTH} characters)")
    description = (description or "").strip() or None
    if description is not None and len(description) > MAX_NAME_LENGTH:
        raise ProtectedTermsConfigError(f"The description is too long (max {MAX_NAME_LENGTH} characters)")
    return {
        "name": name,
        "description": description,
        "terms": _clean_term_list(terms, "terms"),
        "exclude_terms": _clean_term_list(exclude_terms, "exclude_terms"),
    }


def validate_protected_terms_config(raw: dict, report_org_id: str) -> dict:
    """Validates a report's own ProtectedTermsConfig before persisting.
    Each `set_ids` entry must resolve to a real ProtectedTermSet in this
    report's own org (mirrors html_template.py's
    validate_resource_bindings cross-org check) -- re-checked here
    server-side even though a manager UI would normally have only
    offered same-org sets to pick from."""
    set_ids = list(dict.fromkeys(raw.get("set_ids") or []))  # de-dup, order-preserving
    if len(set_ids) > MAX_SET_IDS:
        raise ProtectedTermsConfigError(f"A report can select at most {MAX_SET_IDS} protected term sets")
    for set_id in set_ids:
        try:
            term_set = protected_term_sets_store.get_set(set_id)
        except protected_term_sets_store.ProtectedTermSetNotFoundError:
            raise ProtectedTermsConfigError(f"Protected term set {set_id!r} does not exist")
        if term_set["org_id"] != report_org_id:
            raise ProtectedTermsConfigError(f"Protected term set {set_id!r} belongs to a different organization")

    return {
        "set_ids": set_ids,
        "terms": _clean_term_list(raw.get("terms") or [], "this report's own terms"),
        "exclude_terms": _clean_term_list(raw.get("exclude_terms") or [], "this report's own exclude_terms"),
    }


# --- resolving at render time --------------------------------------------


def resolve_protected_terms(config: dict | None) -> tuple[list[str], list[str]]:
    """Returns (inject_terms, exclude_terms) -- the report-specific layer
    only; the deployment-wide floor (built-ins + env vars) is not
    included here, it's merged in one level down by
    aksor_khmer_ocr_segmenter's own `_sorted_terms`.

    A `set_ids` entry that no longer resolves (the set was deleted, or --
    shouldn't happen post-validation, but defence in depth -- moved to
    another org) is skipped and logged, not raised: this resolution is
    best-effort cosmetic behavior (worst case, a word doesn't get
    merge-protected), unlike resource_bindings, where a broken reference
    means required content is actually missing from the document. A
    render should never fail because someone deleted a term set.
    """
    if not config:
        return [], []

    inject: list[str] = list(config.get("terms") or [])
    exclude: list[str] = list(config.get("exclude_terms") or [])
    for set_id in config.get("set_ids") or []:
        try:
            term_set = protected_term_sets_store.get_set(set_id)
        except protected_term_sets_store.ProtectedTermSetNotFoundError:
            _log.warning("Protected term set %r no longer exists -- skipping for this render", set_id)
            continue
        inject.extend(term_set["terms"])
        exclude.extend(term_set["exclude_terms"])
    return inject, exclude
