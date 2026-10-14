"""Dashboards: Analyze views as tiles on one page, with filters shared across them.

Who sees what:
* the owner edits it (making one needs `analyze:use`, and every tile must be a dataset the owner may analyze);
* the roles it's shared with view it -- no `analyze:use` needed, so report viewers can have dashboards too;
* every viewer sees every tile with *their own* access to its dataset: a restricted dataset only gives them their
  grants' values, or nothing (that tile says so) when they have none. Sharing a dashboard never shares data the
  viewer couldn't otherwise get from a restricted dataset -- restrict a dataset to keep its rows from someone.

Shared filters: the dashboard holds filter values by name ({"p_branch": "BR01"}); each tile takes the ones its dataset
has a filter for, on top of its own saved values. The viewer may change them on the page; their access is checked
on every tile run, as on a report run.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select

from . import analyze, datasets, db
from .report_data import DataConfigError, DataSourceError

VIEWS = ("table", "bar", "line", "kpi")
MAX_TILES = 24
TILE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def _roles(session, context) -> set[str]:
    from .rbac import _active_role_ids

    return set(_active_role_ids(session, context.user.id)) if context.user else set()


def can_edit(context, row: db.Dashboard) -> bool:
    return bool(context.is_superuser or (context.user and row.owner_id == context.user.id))


def can_view(session, context, row: db.Dashboard) -> bool:
    if can_edit(context, row):
        return True
    return bool(set(row.shared_role_ids or []) & _roles(session, context))


def visible(session, context, org_id: str) -> list[db.Dashboard]:
    rows = session.scalars(select(db.Dashboard).where(db.Dashboard.org_id == org_id).order_by(db.Dashboard.title))
    return [r for r in rows if can_view(session, context, r)]


def viewer_may_use(session, context, row: db.Dataset) -> bool:
    """A dashboard viewer's access to a tile's dataset: an open one yes (the owner chose to share it), a restricted
    one only with a grant -- `analyze:use` isn't needed to look at a dashboard."""
    if (row.access_mode or "open") != "restricted" or datasets.bypasses(context):
        return True
    return bool(datasets._grants_for(session, context, row.id, datasets.ACCESS_LEVELS))


def check_tiles(session, context, org_id: str, raw: Any) -> list[dict]:
    """The tiles cleaned. Each must be a dataset the editor may analyze, with a layout Analyze accepts."""
    if not isinstance(raw, list):
        raise DataConfigError("tiles must be a list")
    if len(raw) > MAX_TILES:
        raise DataConfigError(f"A dashboard holds at most {MAX_TILES} tiles")
    out: list[dict] = []
    seen: set[str] = set()
    for i, tile in enumerate(raw, start=1):
        if not isinstance(tile, dict):
            raise DataConfigError(f"Tile {i} isn't valid")
        tile_id = str(tile.get("id") or "")
        if not TILE_ID_RE.match(tile_id) or tile_id in seen:
            raise DataConfigError(f"Tile {i} needs an id of its own")
        seen.add(tile_id)
        title = (tile.get("title") or "").strip()
        if not title or len(title) > 120:
            raise DataConfigError(f"Tile {i} needs a title (up to 120 characters)")
        view = tile.get("view") or "table"
        if view not in VIEWS:
            raise DataConfigError(f"Tile {title!r}: show it as a table, a bar or line chart, or a KPI")
        width = tile.get("width") or (1 if view == "kpi" else 2)
        if width not in (1, 2, 3):
            raise DataConfigError(f"Tile {title!r}: its width is 1, 2 or 3 columns")
        dataset = datasets.row_by_name(session, org_id, tile.get("dataset") or "")
        if dataset is None or not analyze.can_use(session, context, dataset):
            raise DataConfigError(f"Tile {title!r}: there's no dataset {tile.get('dataset')!r} you may analyze")
        layout = analyze.check_layout(tile.get("layout") or {}, dataset.fields or [], dataset.measures or [])
        if view == "kpi" and (layout["rows"] or layout["columns"]):
            raise DataConfigError(f"Tile {title!r}: a KPI is one number -- take the fields out of rows and columns")
        values = tile.get("values") or {}
        if not isinstance(values, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in values.items()):
            raise DataConfigError(f"Tile {title!r}: its filter values must be text")
        out.append({"id": tile_id, "title": title, "dataset": dataset.name, "values": values, "layout": layout, "view": view, "width": width})
    return out


def check_filters(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict) or not all(isinstance(k, str) and isinstance(v, str) and len(v) <= 200 for k, v in raw.items()):
        raise DataConfigError("filters must map a filter's name to its value")
    return dict(raw)


def filter_bar(session, context, row: db.Dashboard) -> list[dict]:
    """The filters the dashboard's tiles share, merged by name, each narrowed to the viewer's values and naming the
    tiles it applies to. A filter only one tile has is still offered -- it's that tile's to change."""
    merged: dict[str, dict] = {}
    for tile in row.tiles or []:
        dataset = datasets.row_by_name(session, row.org_id, tile["dataset"])
        if dataset is None or not viewer_may_use(session, context, dataset):
            continue
        try:
            form = analyze.form(session, context, dataset)
        except (analyze.AnalyzeDenied, DataSourceError):  # a tile that can't be set up just doesn't contribute
            continue
        for p in form["parameters"]:
            entry = merged.setdefault(p["name"], {**p, "tiles": []})
            entry["tiles"].append(tile["id"])
            if entry.get("options") is not None and p.get("options") is not None:
                allowed = {o["value"] for o in p["options"]}
                entry["options"] = [o for o in entry["options"] if o["value"] in allowed]
    return list(merged.values())


def run_tile(session, context, row: db.Dashboard, tile_id: str, overrides: dict[str, str]) -> dict:
    """One tile's result for this viewer: its own values, then the dashboard's shared ones, then what the viewer
    changed on the page -- each only for a filter its dataset has. Access is the viewer's (checked in analyze)."""
    tile = next((t for t in row.tiles or [] if t["id"] == tile_id), None)
    if tile is None:
        raise LookupError("tile")
    dataset = datasets.row_by_name(session, row.org_id, tile["dataset"])
    if dataset is None:
        raise DataConfigError(f"The dataset {tile['dataset']!r} this tile shows no longer exists")
    if not viewer_may_use(session, context, dataset):
        raise analyze.AnalyzeDenied(f"You don't have access to the dataset {dataset.title!r} this tile shows")
    names = {p["name"] for p in dataset.parameters or []}
    values = {**tile.get("values", {}), **{k: v for k, v in {**(row.filters or {}), **overrides}.items() if k in names}}
    result = analyze.run(session, context, dataset, values, tile["layout"])
    return {**result, "tile": tile}
