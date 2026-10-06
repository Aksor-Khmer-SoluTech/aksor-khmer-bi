"""A read-only mirror of the deployment-wide Khmer protected-terms floor
(the four AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE/_DIR/EXCLUDED_TERMS_FILE/_DIR
env vars aksor_khmer_ocr_segmenter's segmenter.py reads once at its own
module import time -- see that module's _ENV_INJECT_TERMS/_ENV_EXCLUDE_TERMS).

This table does NOT feed rendering -- the segmenter's own frozen,
process-lifetime lists stay the actual source of truth applied to every
render, unchanged (see specs/protected_terms_design.md's "deliberately not
changing" decision about this floor). It exists purely so that
deployment-wide config, otherwise invisible outside SSH-ing into the
container to read a bind-mounted file, is inspectable/auditable as data.
Synced (never directly written) every API boot -- see
app/deployment_terms_sync.py.

A singleton row (id="default"), not per-org like ProtectedTermSet
(app/db/protected_terms.py) -- the floor genuinely applies to every org
today, so modeling it as org-scoped, user-referenceable data would
misrepresent it as something a manager opts into.
"""
from __future__ import annotations

from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class DeploymentProtectedTerms(Base):
    __tablename__ = "deployment_protected_terms"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # always "default"
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    terms: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    exclude_terms: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Which env vars were set at last sync, for audit ("why does this list
    # look the way it does") -- not secrets, just the same paths already
    # visible in docker-compose.yml.
    source_paths: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    synced_at: Mapped[str] = mapped_column(String, nullable=False)
