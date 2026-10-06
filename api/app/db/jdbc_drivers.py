"""Uploaded JDBC drivers: a vendor's .jar, kept on disk (app/jdbc_drivers.py),
described here. A JDBC connection (app/jdbc.py) names one by id."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _gen_id


class JdbcDriver(Base):
    """One row per uploaded .jar.

    The file itself lives at data/jdbc_drivers/<id>.jar -- named by id, never by
    the uploaded filename, so a name can't point outside the folder or clash.
    `sha256` is what the driver service re-checks before loading it, so a file
    swapped on the shared volume after upload is refused. `name` is what a
    person picks it by; unique within the organization."""

    __tablename__ = "jdbc_drivers"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_jdbc_drivers_org_name"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    engine: Mapped[str] = mapped_column(String, nullable=False)
    driver_class: Mapped[str] = mapped_column(String, nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    sha256: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
