"""Request/response models for JDBC drivers (routers/jdbc.py, app/jdbc_drivers.py).
The upload itself is multipart form data, so only the response is modelled."""
from __future__ import annotations

from pydantic import BaseModel, Field


class JdbcEngineOut(BaseModel):
    id: str
    label: str
    default_port: int
    driver_class: str
    built_in: bool = Field(..., description="Runs without an uploaded driver")
    driver_url: str = Field(..., description="Where the vendor publishes its JDBC driver")
    ssl_note: str
    database_label: str
    ssl_modes: list[str]


class JdbcDriverOut(BaseModel):
    id: str
    org_id: str
    name: str
    engine: str
    driver_class: str
    filename: str
    sha256: str
    size_bytes: int
    used_by: list[str] = Field(default_factory=list, description="Names of the connections that use it")
    created_at: str
