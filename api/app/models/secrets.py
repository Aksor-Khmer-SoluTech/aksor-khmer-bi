"""Request/response models for secrets (routers/secrets.py, app/secrets.py).
The value is never part of any *Out model -- see app/secret_store.py."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, SecretStr


class SecretRef(BaseModel):
    """One thing that refers to a secret by name -- a report's data source or
    choice list, or a connection's own authentication."""

    kind: Literal["report", "connection"]
    name: str
    report_id: str | None = None
    code: str | None = Field(None, description="A report's own code, if it has one -- for a link into the portal")
    connection_id: str | None = None


class SecretCreate(BaseModel):
    org_id: str | None = Field(None, description="Organization the secret belongs to; defaults to the caller's own")
    name: str = Field(
        ...,
        max_length=64,
        description="What a data source's or connection's token_secret/password_secret refers to it by: lowercase "
        "letters, digits and single hyphens/underscores. Fixed once created",
    )
    description: str | None = Field(None, max_length=500)
    value: SecretStr = Field(..., description="The credential itself. Never returned by any endpoint")


class SecretRotate(BaseModel):
    value: SecretStr = Field(..., description="Replaces the stored value; whatever already names this secret needs no change")


class SecretUpdate(BaseModel):
    description: str | None = Field(None, max_length=500)
    is_active: bool | None = Field(
        None,
        description="false revokes it: whatever still refers to it by name keeps existing, but resolving it at run "
        "time then fails with a readable error, instead of silently using a stale value. true reactivates it.",
    )


class SecretSummary(BaseModel):
    id: str
    org_id: str
    name: str
    description: str | None = None
    is_active: bool
    used_by_count: int = Field(..., description="Reports and connections that currently refer to this secret by name")
    created_at: str
    updated_at: str


class SecretOut(SecretSummary):
    used_by: list[SecretRef]
