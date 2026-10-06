"""Uploaded JDBC drivers -- a vendor's .jar for an engine the server has no
built-in driver for (Oracle, SQL Server, Db2, ...), or one a manager would
rather use than the built-in.

A .jar is code, and loading it runs it. So the API never does: it only stores
the file (data/jdbc_drivers/<id>.jar, mounted read-only into the `jdbc-worker`
service) and checks that it is plausible -- a zip that really contains the
driver class it was declared with, under a size cap. Whoever may upload one
(`driver:manage`) is trusted the way someone who can deploy code is, which is
why that permission is separate from `connection:manage` and not in any role
but the organization administrator's. Each upload's SHA-256 is shown and
audited, and the worker refuses a file whose hash no longer matches.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import select

from . import db
from .jdbc import ENGINES
from .rbac import ROOT_ORG_ID
from .report_data import DataConfigError, DataSourceError

_log = logging.getLogger("aksor_khmer_bi.jdbc_drivers")

# api/app/jdbc_drivers.py -> parents[2] is the repo root, same as report_store.
_REPO_ROOT = Path(__file__).resolve().parents[2]
DRIVER_DIR = _REPO_ROOT / "data" / "jdbc_drivers"

MAX_BYTES = int(os.environ.get("JDBC_DRIVER_MAX_MB", "80")) * 1024 * 1024
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()\-]{0,78}[A-Za-z0-9)]$")
_CLASS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)+$")


def path_for(driver_id: str) -> Path:
    return DRIVER_DIR / f"{driver_id}.jar"


def validate_meta(name: str, engine: str, driver_class: str | None) -> tuple[str, str, str]:
    cleaned = (name or "").strip()
    if not NAME_RE.match(cleaned):
        raise DataConfigError("Name the driver with 2-80 letters, digits, spaces or . _ - ( ) -- e.g. Oracle 23 (ojdbc11)")
    if engine not in ENGINES:
        raise DataConfigError(f"Database engine {engine!r} isn't supported")
    klass = (driver_class or "").strip() or ENGINES[engine].driver_class
    if not _CLASS_RE.match(klass):
        raise DataConfigError(f"{klass!r} isn't a Java class name -- e.g. {ENGINES[engine].driver_class}")
    return cleaned, engine, klass


def save_upload(driver_id: str, source: BinaryIO, driver_class: str) -> tuple[str, int]:
    """Write the upload to DRIVER_DIR as <id>.jar after checking it. Returns
    (sha256, size). Raises DataConfigError, leaving nothing behind."""
    DRIVER_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=DRIVER_DIR, prefix=".upload.")
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(fd, "wb") as handle:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise DataConfigError(f"That file is larger than {MAX_BYTES // (1024 * 1024)} MB -- a JDBC driver is rarely over a few")
                digest.update(chunk)
                handle.write(chunk)
        if size == 0:
            raise DataConfigError("That file is empty")
        if not zipfile.is_zipfile(tmp):
            raise DataConfigError("That isn't a .jar file (a JDBC driver is a zip archive)")
        entry = driver_class.replace(".", "/") + ".class"
        try:
            with zipfile.ZipFile(tmp) as jar:
                names = set(jar.namelist())
        except zipfile.BadZipFile as exc:
            raise DataConfigError("That .jar is damaged") from exc
        if entry not in names:
            raise DataConfigError(
                f"That .jar doesn't contain {driver_class} -- check the driver class, or that it is the right driver for this engine"
            )
        os.chmod(tmp, 0o644)
        os.replace(tmp, path_for(driver_id))
        return digest.hexdigest(), size
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def remove_file(driver_id: str) -> None:
    try:
        path_for(driver_id).unlink()
    except FileNotFoundError:
        pass


def engines_by_id(org_id: str | None) -> dict[str, dict]:
    """{driver id: {"engine": ...}} for an organization -- what a connection's
    driver choice is checked against."""
    with db.SessionLocal() as session:
        rows = session.execute(
            select(db.JdbcDriver.id, db.JdbcDriver.engine).where(db.JdbcDriver.org_id == (org_id or ROOT_ORG_ID))
        )
        return {row.id: {"engine": row.engine} for row in rows}


def describe(driver_id: str, org_id: str | None) -> dict:
    """What the worker needs to load one driver. Raises DataSourceError (safe to
    show whoever runs the report) if it was deleted from under a connection."""
    with db.SessionLocal() as session:
        row = session.get(db.JdbcDriver, driver_id)
    if row is None or row.org_id != (org_id or ROOT_ORG_ID):
        _log.error("JDBC driver %r no longer exists in organization %r", driver_id, org_id)
        raise DataSourceError("This report's database driver no longer exists -- ask whoever manages connections")
    return {"file": path_for(row.id).name, "sha256": row.sha256, "class_name": row.driver_class}


def used_by(session, driver_id: str) -> list[str]:
    """Names of the connections that use a driver."""
    return [
        row.name
        for row in session.scalars(select(db.DataConnection).where(db.DataConnection.kind == "jdbc"))
        if (row.config or {}).get("driver_id") == driver_id
    ]
