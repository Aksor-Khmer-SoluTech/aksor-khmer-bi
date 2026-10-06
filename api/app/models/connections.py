"""Request/response models for connections (routers/connections.py, app/connections.py)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .reports import DataSourceAuth


class RestConnectionConfig(BaseModel):
    base_url: str = Field(..., description="http(s) scheme and host, optionally a path prefix: https://erp.example.com/api")
    headers: dict[str, str] | None = Field(None, description="Sent with every call through this connection")
    auth: DataSourceAuth | None = Field(
        None,
        description="How to authenticate: name an environment variable on the API server (token_env / password_env), "
        "or a Secret managed in the portal (token_secret / password_secret -- Admin > Secrets)",
    )


class JdbcConnectionConfig(BaseModel):
    """A relational database, reached with a JDBC-style URL. The credential is
    the same Secret (or environment-variable name) shape a REST connection
    uses -- the password itself is never part of this config (see
    app/secrets.py), so it is never returned, audited or logged."""

    engine: str = Field(..., description="oracle, postgresql, mysql, sqlserver, mariadb or db2")
    host: str
    port: int = Field(..., ge=1, le=65535)
    database: str = Field("", description="Database name; for Oracle the service name or SID")
    service_type: Literal["service_name", "sid"] | None = Field(None, description="Oracle only")
    ssl_mode: Literal["disable", "require", "verify-ca", "verify-full"] = "disable"
    driver_id: str | None = Field(
        None,
        description="An uploaded JDBC driver (Admin > JDBC drivers). Omit to use the built-in driver, which "
        "PostgreSQL, MySQL and MariaDB have",
    )
    jdbc_url: str | None = Field(
        None, description="A complete JDBC URL, used instead of one built from the fields above; only with an uploaded driver"
    )
    auth: DataSourceAuth = Field(..., description="Username and a password_secret (or password_env); type is always basic")


class ConnectionReportRef(BaseModel):
    report_id: str
    name: str
    code: str | None = None


class ConnectionCreate(BaseModel):
    org_id: str | None = Field(None, description="Organization the connection belongs to; defaults to the caller's own")
    name: str = Field(
        ...,
        max_length=64,
        description="What reports refer to it by: lowercase letters, digits and single hyphens/underscores. Fixed once created",
    )
    kind: Literal["rest", "jdbc"] = "rest"
    description: str | None = Field(None, max_length=500)
    config: RestConnectionConfig | JdbcConnectionConfig


class ConnectionUpdate(BaseModel):
    """Replaced wholesale (the name and kind are fixed -- reports refer to them)."""

    description: str | None = Field(None, max_length=500)
    config: RestConnectionConfig | JdbcConnectionConfig


class ConnectionSummary(BaseModel):
    """What a report author needs to choose a connection: no header values --
    they may hold client identifiers or keys, and only a connection manager
    edits them (GET /connections/{id})."""

    id: str
    org_id: str
    name: str
    kind: str
    description: str | None = None
    base_url: str = Field(..., description="A REST connection's base URL, or a JDBC connection's URL (no credentials in it)")
    engine: str | None = Field(None, description="JDBC connections only")
    auth_type: Literal["none", "bearer", "basic"]
    credential: Literal["none", "secret", "env"] = Field(
        "none",
        description="Where the credential comes from: a Secret managed in the portal, or an environment variable on "
        "the server (whose name only a connection manager sees)",
    )
    secret_name: str | None = Field(None, description="The Secret's name, when `credential` is 'secret'")
    header_names: list[str]
    report_count: int = Field(..., description="Reports whose data source or choice lists go through this connection")
    updated_at: str


class ConnectionOut(BaseModel):
    id: str
    org_id: str
    name: str
    kind: str
    description: str | None = None
    config: RestConnectionConfig | JdbcConnectionConfig
    reports: list[ConnectionReportRef]
    created_at: str
    updated_at: str


class ConnectionTest(BaseModel):
    """Body of POST /connections/test: try a JDBC connection's settings --
    saved or not -- without saving anything."""

    org_id: str | None = Field(None, description="Organization whose Secrets and drivers apply; defaults to the caller's own")
    config: JdbcConnectionConfig


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str
    elapsed_ms: int | None = None
