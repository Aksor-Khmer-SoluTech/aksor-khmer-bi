"""Request/response models for API clients (routers/clients.py, specs/api_clients_design.md)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..clients import CLIENT_ID_PATTERN


class ClientReportRef(BaseModel):
    report_id: str
    name: str
    code: str | None = None


class ClientCreate(BaseModel):
    org_id: str | None = Field(None, description="Organization the client belongs to; defaults to the caller's own")
    client_id: str = Field(
        ...,
        min_length=3,
        max_length=64,
        pattern=CLIENT_ID_PATTERN,
        description="What the caller sends with the secret: lowercase letters, digits and single hyphens. Unique across organizations.",
    )
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    report_ids: list[str] = Field(default_factory=list, description="Reports the client may run")


class ClientUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    is_active: bool | None = None


class ClientReportsUpdate(BaseModel):
    report_ids: list[str]


class ClientOut(BaseModel):
    """Never carries the secret -- only a short prefix to tell secrets apart."""

    id: str
    org_id: str
    client_id: str
    name: str
    description: str | None = None
    is_active: bool
    secret_prefix: str
    created_at: str
    secret_rotated_at: str | None = None
    last_used_at: str | None = None
    reports: list[ClientReportRef]


class ClientWithSecret(BaseModel):
    """The one response that carries a secret (create, rotate). It can't be shown again."""

    client: ClientOut
    secret: str
