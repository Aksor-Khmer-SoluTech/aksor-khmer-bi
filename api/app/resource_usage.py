"""Which templates use an image or a stylesheet -- the Resources details panel's "Used by", and a warning before a
file everyone shares is replaced or deleted.

A template uses a resource in one of two ways:
* an html template maps a `resource('logo')` name to it (its resource_bindings) -- "as logo";
* a template's data points at an image: {"image_id": …} in its sample data or a static data source (a Word picture).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from . import db


def _image_ids(value: Any, out: set[str]) -> None:
    if isinstance(value, dict):
        if isinstance(value.get("image_id"), str):
            out.add(value["image_id"])
        for v in value.values():
            _image_ids(v, out)
    elif isinstance(value, list):
        for v in value:
            _image_ids(v, out)


def used_by(kind: str, resource_id: str, org_id: str) -> list[dict]:
    """[{report_id, name, template_ext, as: [resource() names], in_data: bool}] for every template here using it."""
    out = []
    with db.SessionLocal() as session:
        for rep in session.execute(select(db.ReportRow).where(db.ReportRow.org_id == org_id).order_by(db.ReportRow.name)).scalars():
            names = sorted(n for n, b in (rep.resource_bindings or {}).items() if b.get("kind") == kind and b.get("id") == resource_id)
            in_data = False
            if kind == "image":
                ids: set[str] = set()
                _image_ids(rep.sample_context, ids)
                _image_ids(rep.data_source, ids)
                in_data = resource_id in ids
            if names or in_data:
                out.append({"report_id": rep.report_id, "name": rep.name, "template_ext": rep.template_ext, "as": names, "in_data": in_data})
    return out
