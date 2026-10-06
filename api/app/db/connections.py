"""Connections -- a named, org-scoped place a report's data comes from: a
REST API's base URL, the headers every call to it carries, and how it is
authenticated. A report's data source or a parameter's choice list names one
(ReportRow.data_source["connection"], ...options_source["connection"]) and only
adds a path, so moving an API to another host -- or dev to production -- is
one edit here instead of one per report. See app/connections.py.
"""
from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _gen_id


class DataConnection(Base):
    """One row per connection.

    `name` is what reports refer to, so it is fixed once created and unique
    within the organization; the same name in two organizations (or two
    environments) can point at different hosts. `kind` says how to read
    `config`: only "rest" exists today -- {"base_url", "headers", "auth"}, the
    same header and auth shapes a report's own data source uses -- and a JDBC
    kind would add its own config shape without another table. Credentials are
    never a value in `config`: either the *name* of an environment variable, or
    the *name* of a Secret (app/db/secrets.py, app/secrets.py) resolved at run
    time -- the same convention a report's own data source uses.
    """

    __tablename__ = "data_connections"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_data_connections_org_name"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="rest")
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
