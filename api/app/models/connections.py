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


class RoutineParameter(BaseModel):
    name: str = Field(..., description="As SQL Server names it, with its @: @branch")
    type: str | None = Field(None, description="Its SQL type, as shown (nvarchar(50), date) -- for the author's information")


class ApprovedRoutine(BaseModel):
    """A stored procedure or function a connection manager allows reports to call (app/routines.py)."""

    name: str = Field(..., description="schema.name, e.g. dbo.GetSalesByBranch")
    kind: Literal["procedure", "table_function", "scalar_function"]
    parameters: list[RoutineParameter] = Field(default_factory=list)


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
    routines: list[ApprovedRoutine] | None = Field(
        None,
        description="SQL Server: the stored procedures and functions reports may call. Omitted on an update: kept as they "
        "are (they have their own endpoint, PUT /connections/{id}/routines)",
    )


class SmtpConnectionConfig(BaseModel):
    """A mail server that jobs send reports through (app/mailer.py). The password, as for every connection, is a
    Secret's name (or an environment variable's) -- never a value."""

    host: str = Field(..., description="e.g. smtp.gmail.com, smtp.office365.com")
    port: int = Field(..., ge=1, le=65535, description="587 for STARTTLS, 465 for TLS")
    security: Literal["starttls", "tls", "none"] = "starttls"
    from_address: str = Field(..., description="The address reports are sent from")
    from_name: str | None = Field(None, description="The sender's name people see, e.g. Aksor Khmer BI")
    auth: DataSourceAuth | None = Field(None, description="Username and a password_secret (or password_env); none for an internal relay")


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
    kind: Literal["rest", "jdbc", "smtp"] = "rest"
    description: str | None = Field(None, max_length=500)
    config: RestConnectionConfig | JdbcConnectionConfig | SmtpConnectionConfig


class ConnectionUpdate(BaseModel):
    """Replaced wholesale (the name and kind are fixed -- reports refer to them)."""

    description: str | None = Field(None, max_length=500)
    config: RestConnectionConfig | JdbcConnectionConfig | SmtpConnectionConfig


class ConnectionSummary(BaseModel):
    """What a report author needs to choose a connection: no header values --
    they may hold client identifiers or keys, and only a connection manager
    edits them (GET /connections/{id})."""

    id: str
    org_id: str
    name: str
    kind: str
    description: str | None = None
    base_url: str = Field(..., description="A REST connection's base URL, a JDBC connection's URL, or a mail server's address and sender (no credentials in any)")
    engine: str | None = Field(None, description="JDBC connections only")
    auth_type: Literal["none", "bearer", "basic"]
    credential: Literal["none", "secret", "env"] = Field(
        "none",
        description="Where the credential comes from: a Secret managed in the portal, or an environment variable on "
        "the server (whose name only a connection manager sees)",
    )
    secret_name: str | None = Field(None, description="The Secret's name, when `credential` is 'secret'")
    header_names: list[str]
    routines: list[ApprovedRoutine] = Field(default_factory=list, description="SQL Server: what reports may call")
    report_count: int = Field(..., description="Reports whose data source or choice lists go through this connection")
    updated_at: str


class ConnectionOut(BaseModel):
    id: str
    org_id: str
    name: str
    kind: str
    description: str | None = None
    config: RestConnectionConfig | JdbcConnectionConfig | SmtpConnectionConfig
    reports: list[ConnectionReportRef]
    created_at: str
    updated_at: str


class ConnectionTest(BaseModel):
    """Body of POST /connections/test: try a JDBC connection's settings --
    saved or not -- without saving anything."""

    org_id: str | None = Field(None, description="Organization whose Secrets and drivers apply; defaults to the caller's own")
    config: JdbcConnectionConfig


class MailServerTest(BaseModel):
    """Body of POST /connections/test-mail: send one test email with a Mail Server's settings -- saved or not."""

    org_id: str | None = Field(None, description="Organization whose Secrets apply; defaults to the caller's own")
    config: SmtpConnectionConfig
    to: str = Field(..., description="Where to send the test email")


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str
    elapsed_ms: int | None = None


class RoutinesUpdate(BaseModel):
    routines: list[ApprovedRoutine]


class DiscoveredRoutines(BaseModel):
    routines: list[ApprovedRoutine]
    can_write: bool = Field(..., description="The connection's login could change data -- it should only read and execute")
    skipped_output: list[str] = Field(default_factory=list, description="Routines left out: they have OUTPUT parameters")
