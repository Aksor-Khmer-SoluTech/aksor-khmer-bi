"""Mirrors the deployment-wide Khmer protected-terms floor into the
database every API boot -- see app/db/deployment_terms.py's module
docstring for what this is and, more importantly, what it deliberately
is NOT (an input to rendering).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .db import DeploymentProtectedTerms

_SINGLETON_ID = "default"


def _row_to_dict(row: DeploymentProtectedTerms) -> dict:
    return {
        "id": row.id,
        "version": row.version,
        "terms": row.terms,
        "exclude_terms": row.exclude_terms,
        "source_paths": row.source_paths,
        "synced_at": row.synced_at,
    }


def snapshot(session: Session) -> dict | None:
    """The floor as currently stored (None before the first ever sync) --
    taken just before a sync so record_change can say what it changed."""
    row = session.get(DeploymentProtectedTerms, _SINGLETON_ID)
    return None if row is None else {"version": row.version, "terms": list(row.terms), "exclude_terms": list(row.exclude_terms)}


def record_change(before: dict | None, after: dict) -> None:
    """Audit a floor that moved between two boots. Unlike every other change
    in the trail this one is made *outside* the API -- someone edited the
    mounted terms file on the host and restarted -- which is precisely why
    it's worth a row: nothing else records it. Called after the sync's
    transaction has committed (a second connection can't write while the
    first still holds SQLite's write lock). The very first sync is the
    baseline, not a change."""
    from . import audit

    if before is None or before["version"] == after["version"]:
        return
    changes = audit.diff(before, after, ["terms", "exclude_terms"])
    audit.record(
        audit.SYSTEM, "deployment_terms.change", "deployment_terms", _SINGLETON_ID,
        label="Deployment-wide protected terms", org_id=None,
        summary=f"Deployment protected-terms files changed (v{before['version']} → v{after['version']})",
        changes=changes, details={"source_paths": after["source_paths"]},
    )


def sync_deployment_terms(session: Session) -> dict:
    """Re-reads the same env-var-pointed files/dirs the segmenter package
    reads once at its own import time (aksor_khmer_ocr_segmenter's
    protected_terms.loader) and upserts a DB record of the current
    deployment-wide floor, bumping `version` only when the effective set
    of terms actually changed since the last sync -- read-only audit
    data, not a new input to rendering (the segmenter's own frozen
    _ENV_INJECT_TERMS/_ENV_EXCLUDE_TERMS, computed once at ITS import
    time, remain the only thing every render actually uses -- see
    specs/protected_terms_design.md's "deliberately not changing"
    decision about this floor). Run every boot, right alongside
    seed_defaults(), so a config-file edit + container restart shows up
    here with no extra step. Caller commits.
    """
    from aksor_khmer_ocr_segmenter.protected_terms import loader

    terms = sorted(set(loader.load_terms_from_env()) | set(loader.load_terms_from_dirs_env()))
    exclude_terms = sorted(set(loader.load_exclusions_from_env()) | set(loader.load_exclusions_from_dirs_env()))
    source_paths = {
        "terms_file": os.environ.get(loader.INJECT_ENV_VAR),
        "terms_dir": os.environ.get(loader.INJECT_DIR_ENV_VAR),
        "exclude_file": os.environ.get(loader.EXCLUDE_ENV_VAR),
        "exclude_dir": os.environ.get(loader.EXCLUDE_DIR_ENV_VAR),
    }
    now = datetime.now(timezone.utc).isoformat()

    row = session.get(DeploymentProtectedTerms, _SINGLETON_ID)
    if row is None:
        row = DeploymentProtectedTerms(
            id=_SINGLETON_ID,
            version=1,
            terms=terms,
            exclude_terms=exclude_terms,
            source_paths=source_paths,
            synced_at=now,
        )
        session.add(row)
    else:
        changed = set(row.terms) != set(terms) or set(row.exclude_terms) != set(exclude_terms)
        row.terms = terms
        row.exclude_terms = exclude_terms
        row.source_paths = source_paths
        row.synced_at = now
        if changed:
            row.version += 1
    session.flush()
    return _row_to_dict(row)
