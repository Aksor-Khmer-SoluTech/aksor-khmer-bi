"""Projects: a top-level Resources folder marked as a project, moved between environments as one package.

A project holds templates (docx, xlsx, html), the images and stylesheets filed in it, and subfolders. Export packs
them -- with what the templates use from outside the project (a shared logo or stylesheet, a runtime font, a
protected-term set), each of which the deployer may leave out when the target already has it -- into one zip with
a manifest. Import reads a package, shows what would happen to every item, and applies the deployer's choices.

How things are matched on the target:
* a file is the same when its content is (sha256) -- an identical image is linked, never copied again;
* a file with the same name but different content is the deployer's call: overwrite it (same id, so every template
  using it changes too), keep both (the import gets its own copy, inside the project), or use the existing one;
* a template is the same report when it has the same code, or else the same name in the same project folder --
  importing it again adds a version to it rather than a second report.

References are re-linked: a template points at resources by id (an html template's resource mapping, a Word
template's {"image_id": …} in its data), and ids differ between environments -- the package carries keys instead.

Never in a package: secrets. A data source names its connection and its secrets; import warns about any the target
doesn't have yet, so they can be created there.

Who may: export needs `project:transfer` and manage access on the project; import needs `project:transfer` and
`report:manage`, plus `font:manage` to add or replace a font and `protected_terms:manage` for term sets.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import shutil
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from . import db, font_catalog, image_store, report_store, stylesheet_store
from . import protected_term_sets_store as term_store

FORMAT = 1
KIND = "aksor-project"
MAX_PACKAGE_BYTES = 200 * 1024 * 1024
MAX_UNPACKED_BYTES = 600 * 1024 * 1024
TOKEN_SECONDS = 3600
IMPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "project_imports"
_REF = "aksor-resource:"  # an image reference inside a template's data, in a package: {"image_id": "aksor-resource:r3"}
_TOKEN_RE = re.compile(r"^[a-f0-9]{32}$")
_EXT_MIME = {"png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp"}


class ProjectError(ValueError):
    """Something about a project or a package the caller can fix (400)."""


class NotAProject(ProjectError):
    pass


# --- what a project holds ----------------------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def project_row(session, folder_id: str) -> db.Folder:
    row = session.get(db.Folder, folder_id)
    if row is None:
        raise LookupError("project")
    if not row.is_project:
        raise NotAProject("This folder isn't a project -- mark it as one first")
    return row


def _tree(session, root: db.Folder) -> dict[str, str]:
    """{folder id: its path inside the project} -- "" for the project itself, "Forms/2026" for a subfolder."""
    paths = {root.id: ""}
    frontier = [root.id]
    while frontier:
        children = session.execute(select(db.Folder).where(db.Folder.parent_folder_id.in_(frontier))).scalars().all()
        frontier = []
        for child in children:
            parent = paths[child.parent_folder_id]
            paths[child.id] = f"{parent}/{child.name}" if parent else child.name
            frontier.append(child.id)
    return paths


def folder_path(session, folder_id: str | None) -> str:
    """Where a resource outside the project lives, for people: "Shared/Logos", or "(top level)"."""
    parts = []
    while folder_id:
        row = session.get(db.Folder, folder_id)
        if row is None:
            break
        parts.append(row.name)
        folder_id = row.parent_folder_id
    return "/".join(reversed(parts)) or "(top level)"


def _image_ids_in(value: Any, out: set[str]) -> None:
    """Every {"image_id": …} a template's data points at (a Word template's pictures)."""
    if isinstance(value, dict):
        if isinstance(value.get("image_id"), str):
            out.add(value["image_id"])
        for v in value.values():
            _image_ids_in(v, out)
    elif isinstance(value, list):
        for v in value:
            _image_ids_in(v, out)


def _references(value: Any, out: dict[str, set[str]]) -> None:
    """Connections, secrets and datasets a data source names (never their contents)."""
    if isinstance(value, dict):
        for key, v in value.items():
            if isinstance(v, str) and v:
                if key == "connection":
                    out["connections"].add(v)
                elif key in ("token_secret", "password_secret", "secret"):
                    out["secrets"].add(v)
                elif key == "dataset" and value.get("type") == "dataset":
                    out["datasets"].add(v)
            _references(v, out)
    elif isinstance(value, list):
        for v in value:
            _references(v, out)


def _uploaded_fonts(session) -> dict[str, list[db.FontResource]]:
    by_family: dict[str, list[db.FontResource]] = {}
    for row in session.execute(select(db.FontResource)).scalars():
        by_family.setdefault(row.family_key, []).append(row)
    return by_family


def contents(folder_id: str) -> dict:
    """Everything a project holds and uses -- the export screen, and what export packs."""
    with db.SessionLocal() as session:
        root = project_row(session, folder_id)
        paths = _tree(session, root)
        reports = session.execute(select(db.ReportRow).where(db.ReportRow.folder_id.in_(list(paths))).order_by(db.ReportRow.name)).scalars().all()
        images = {r.id: r for r in session.execute(select(db.ImageResource).where(db.ImageResource.folder_id.in_(list(paths)))).scalars()}
        sheets = {r.id: r for r in session.execute(select(db.StylesheetResource).where(db.StylesheetResource.folder_id.in_(list(paths)))).scalars()}
        fonts_by_family = _uploaded_fonts(session)

        resources: dict[tuple[str, str], dict] = {}  # (kind, id) -> entry

        def resource(kind: str, rid: str, used_by: str | None) -> dict | None:
            key = (kind, rid)
            if key not in resources:
                row = (images.get(rid) if kind == "image" else sheets.get(rid)) or session.get(db.ImageResource if kind == "image" else db.StylesheetResource, rid)
                if row is None or row.org_id != root.org_id:
                    return None
                inside = row.folder_id in paths
                resources[key] = {
                    "kind": kind, "id": row.id, "name": row.name, "size_bytes": row.size_bytes,
                    "scope": "project" if inside else "shared",
                    "folder": paths[row.folder_id] if inside else None,
                    "where": root.name + ("/" + paths[row.folder_id] if paths.get(row.folder_id) else "") if inside else folder_path(session, row.folder_id),
                    "used_by": [],
                }
            entry = resources[key]
            if used_by and used_by not in entry["used_by"]:
                entry["used_by"].append(used_by)
            return entry

        for row in images.values():
            resource("image", row.id, None)
        for row in sheets.values():
            resource("stylesheet", row.id, None)

        templates, missing, fonts, term_sets = [], [], {}, {}
        references: dict[str, set[str]] = {"connections": set(), "secrets": set(), "datasets": set()}
        for rep in reports:
            used: set[str] = set()
            for name, binding in (rep.resource_bindings or {}).items():
                if resource(binding.get("kind"), binding.get("id"), rep.name) is None:
                    missing.append(f"{rep.name}: resource {name!r} points at something that no longer exists")
                else:
                    used.add(f"{binding.get('kind')}:{binding.get('id')}")
            image_ids: set[str] = set()
            _image_ids_in(rep.sample_context, image_ids)
            _image_ids_in(rep.data_source, image_ids)
            for image_id in image_ids:
                if resource("image", image_id, rep.name) is None:
                    missing.append(f"{rep.name}: its data points at an image ({image_id}) that no longer exists")
            _references(rep.data_source, references)
            _references(rep.parameters, references)
            for set_id in (rep.protected_terms_config or {}).get("set_ids") or []:
                term = session.get(db.ProtectedTermSet, set_id)
                if term is not None:
                    term_sets.setdefault(term.id, {"id": term.id, "name": term.name, "terms": len(term.terms or []), "used_by": []})["used_by"].append(rep.name)
            # Fonts it names (and, for html, the stylesheets it uses name) that were added under Resources > Fonts.
            named: set[str] = set()
            try:
                named.update(font_catalog.fonts_named_by(report_store._template_path(rep.report_id, rep.template_ext), rep.template_ext))
            except Exception:  # noqa: BLE001 -- an unreadable template just names no fonts
                pass
            for key in used:
                kind, rid = key.split(":", 1)
                if kind == "stylesheet":
                    try:
                        named.update(font_catalog._html_fonts(stylesheet_store.get_stylesheet_bytes(rid).decode("utf-8", "replace")))
                    except stylesheet_store.StylesheetNotFoundError:
                        pass
            for family in named:
                for font in fonts_by_family.get(family.lower(), []):
                    fonts.setdefault(font.id, {"id": font.id, "family": font.family, "subfamily": font.subfamily, "used_by": []})["used_by"].append(rep.name)
            templates.append({
                "id": rep.report_id, "name": rep.name, "template_ext": rep.template_ext, "code": rep.code,
                "folder": paths.get(rep.folder_id, ""), "version": rep.version, "is_draft": rep.is_draft,
            })
        listed = sorted(resources.values(), key=lambda r: (r["scope"] != "project", r["kind"], r["name"].lower()))
        return {
            "project": {"id": root.id, "name": root.name, "description": root.description, "org_id": root.org_id},
            "folders": sorted(p for p in paths.values() if p),
            "templates": templates,
            "resources": listed,
            "fonts": sorted(fonts.values(), key=lambda f: (f["family"], f["subfamily"])),
            "term_sets": sorted(term_sets.values(), key=lambda t: t["name"]),
            "references": {k: sorted(v) for k, v in references.items()},
            "warnings": missing,
        }


# --- export ------------------------------------------------------------------------------------------------------


def export(folder_id: str, *, leave_out: set[str], versions: bool, data_sources: bool, fonts: bool, term_sets: bool, who: str) -> tuple[bytes, dict]:
    """The package (zip bytes) and its manifest. `leave_out`: "image:<id>"/"stylesheet:<id>" of shared resources the
    target already has -- recorded by name and fingerprint so import can find them, but not packed."""
    info = contents(folder_id)
    with db.SessionLocal() as session:
        reports = {r.report_id: r for r in session.execute(select(db.ReportRow).where(db.ReportRow.report_id.in_([t["id"] for t in info["templates"]]))).scalars()}
    out = io.BytesIO()
    keys: dict[str, str] = {}  # "image:<id>" -> package key
    manifest: dict[str, Any] = {
        "kind": KIND, "format": FORMAT, "exported_at": _now(), "exported_by": who,
        "project": {"name": info["project"]["name"], "description": info["project"]["description"]},
        "folders": info["folders"],
        "contains": {"versions": versions, "data_sources": data_sources, "fonts": fonts, "term_sets": term_sets},
        "resources": [], "templates": [], "fonts": [], "term_sets": [],
        "references": info["references"] if data_sources else {"connections": [], "secrets": [], "datasets": []},
    }
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for n, res in enumerate(info["resources"], start=1):
            key = f"r{n}"
            keys[f"{res['kind']}:{res['id']}"] = key
            if res["kind"] == "image":
                meta = image_store.get_image(res["id"])
                content, ext, sha = image_store.get_image_bytes(res["id"]), meta["file_ext"], image_store.fingerprint(res["id"])
            else:
                # The upload itself -- SCSS stays SCSS, and is compiled again on the other server.
                (content, ext), sha = stylesheet_store.get_stylesheet_source(res["id"]), stylesheet_store.fingerprint(res["id"])
            packed = res["scope"] == "project" or f"{res['kind']}:{res['id']}" not in leave_out
            path = f"resources/{key}.{ext}" if packed else None
            if path:
                zf.writestr(path, content)
            manifest["resources"].append({
                "key": key, "kind": res["kind"], "name": res["name"], "scope": res["scope"], "folder": res["folder"],
                "sha256": sha, "file": path, "ext": ext, "used_by": res["used_by"],
            })
        term_keys: dict[str, str] = {}
        if term_sets:
            for n, entry in enumerate(info["term_sets"], start=1):
                row = term_store.get_set(entry["id"])
                term_keys[entry["id"]] = f"ts{n}"
                manifest["term_sets"].append({"key": f"ts{n}", "name": row["name"], "description": row.get("description"),
                                              "terms": row.get("terms") or [], "exclude_terms": row.get("exclude_terms") or []})
        if fonts:
            with db.SessionLocal() as session:
                for n, entry in enumerate(info["fonts"], start=1):
                    row = session.get(db.FontResource, entry["id"])
                    from . import font_store

                    path = font_store.path_for(row.id, row.file_ext)
                    if not path.exists():
                        continue
                    zf.writestr(f"fonts/f{n}.{row.file_ext}", path.read_bytes())
                    manifest["fonts"].append({"key": f"f{n}", "family": row.family, "subfamily": row.subfamily, "sha256": row.sha256,
                                              "file": f"fonts/f{n}.{row.file_ext}", "filename": row.filename, "note": row.note})
        for n, entry in enumerate(info["templates"], start=1):
            rep = reports[entry["id"]]
            key = f"t{n}"
            current = report_store._template_path(rep.report_id, rep.template_ext)
            zf.writestr(f"templates/{key}/current.{rep.template_ext}", current.read_bytes())
            history = []
            if versions:
                for v in reversed(report_store.list_versions(rep.report_id)):  # oldest first
                    if v["version"] == rep.version or not v["available"]:
                        continue
                    vpath, _ = report_store.get_version_file(rep.report_id, v["version"])
                    name = f"templates/{key}/v{v['version']}.{v['template_ext']}"
                    zf.writestr(name, vpath.read_bytes())
                    history.append({"version": v["version"], "label": v["version_label"], "note": v["note"], "created_at": v["created_at"],
                                    "template_ext": v["template_ext"], "file": name})
            current_info = next((v for v in report_store.list_versions(rep.report_id) if v["version"] == rep.version), {})
            bindings = {name: {"kind": b.get("kind"), "ref": keys.get(f"{b.get('kind')}:{b.get('id')}")} for name, b in (rep.resource_bindings or {}).items()}
            terms_cfg = rep.protected_terms_config or {}
            manifest["templates"].append({
                "key": key, "name": rep.name, "description": rep.description, "code": rep.code, "template_ext": rep.template_ext,
                "folder": entry["folder"], "is_draft": rep.is_draft, "is_public": rep.is_public,
                "file": f"templates/{key}/current.{rep.template_ext}", "version": rep.version,
                "version_label": current_info.get("version_label"), "note": current_info.get("note"),
                "history": history,
                "resource_bindings": bindings,
                "parameters": rep.parameters if data_sources else None,
                "data_source": _to_refs(rep.data_source, keys) if data_sources else None,
                "sample_context": _to_refs(rep.sample_context, keys) if data_sources else None,
                "protected_terms": {
                    "set_refs": [term_keys[s] for s in terms_cfg.get("set_ids") or [] if s in term_keys],
                    "terms": terms_cfg.get("terms") or [], "exclude_terms": terms_cfg.get("exclude_terms") or [],
                },
            })
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return out.getvalue(), manifest


def _to_refs(value: Any, keys: dict[str, str]) -> Any:
    """A template's data with each {"image_id": <id>} turned into the package key of that image."""
    value = copy.deepcopy(value)

    def walk(v):
        if isinstance(v, dict):
            if isinstance(v.get("image_id"), str) and f"image:{v['image_id']}" in keys:
                v["image_id"] = _REF + keys[f"image:{v['image_id']}"]
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(value)
    return value


def _from_refs(value: Any, ids: dict[str, str | None]) -> Any:
    value = copy.deepcopy(value)

    def walk(v):
        if isinstance(v, dict):
            ref = v.get("image_id")
            if isinstance(ref, str) and ref.startswith(_REF):
                v["image_id"] = ids.get(ref[len(_REF):]) or ref
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(value)
    return value


# --- reading a package -------------------------------------------------------------------------------------------


class Package:
    """A package, checked: a zip under the size limits, with a manifest naming only files that are in it."""

    def __init__(self, data: bytes):
        if len(data) > MAX_PACKAGE_BYTES:
            raise ProjectError(f"The package is larger than {MAX_PACKAGE_BYTES // (1024 * 1024)} MB")
        try:
            self.zip = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise ProjectError("That isn't a project package (not a .zip file)") from exc
        if sum(i.file_size for i in self.zip.infolist()) > MAX_UNPACKED_BYTES:
            raise ProjectError("The package unpacks to more than the server allows")
        try:
            self.manifest = json.loads(self.zip.read("manifest.json").decode("utf-8"))
        except (KeyError, ValueError) as exc:
            raise ProjectError("That isn't a project package (no manifest.json)") from exc
        if self.manifest.get("kind") != KIND:
            raise ProjectError("That isn't an Aksor project package")
        if self.manifest.get("format") != FORMAT:
            raise ProjectError(f"This package is format {self.manifest.get('format')!r}; this server reads format {FORMAT}")
        self.names = set(self.zip.namelist())

    def read(self, name: str | None) -> bytes | None:
        if not name:
            return None
        if name not in self.names:
            raise ProjectError(f"The package names {name!r} but doesn't contain it")
        return self.zip.read(name)


# --- planning an import ------------------------------------------------------------------------------------------


def _choices(scope: str, status: str) -> list[str]:
    if status == "differs":
        return ["overwrite", "keep_both", "use_existing"]
    if status == "new":
        return ["create"] if scope == "project" else ["create_shared", "create_in_project"]
    if status == "identical_elsewhere":
        return ["link", "copy_into_project"]
    return []


def plan(pkg: Package, org_id: str, *, into: str | None, context) -> dict:
    """What importing `pkg` would do, item by item, with the choices the deployer has. `into`: an existing project's
    folder id to import into, or None for a new project (named as in the package)."""
    m = pkg.manifest
    with db.SessionLocal() as session:
        if into:
            target = project_row(session, into)
            if target.org_id != org_id:
                raise LookupError("project")
            paths = _tree(session, target)
            by_path = {p: fid for fid, p in paths.items()}
        else:
            target, paths, by_path = None, {}, {}
            clash = session.execute(select(db.Folder).where(db.Folder.org_id == org_id, db.Folder.parent_folder_id.is_(None), db.Folder.name == m["project"]["name"])).scalar_one_or_none()
            if clash is not None:
                raise ProjectError(f'There is already a folder named "{m["project"]["name"]}" at the top level -- import into it (if it is the same project), or rename one of them')

        resources = []
        for res in m.get("resources", []):
            model = db.ImageResource if res["kind"] == "image" else db.StylesheetResource
            store = image_store if res["kind"] == "image" else stylesheet_store
            entry = {"key": res["key"], "kind": res["kind"], "name": res["name"], "scope": res["scope"], "included": bool(res.get("file")),
                     "used_by": res.get("used_by", []), "existing": None}
            same = None
            if res["scope"] == "project" and target is not None:
                folder_id = by_path.get(res.get("folder") or "")
                if folder_id:
                    same = session.execute(select(model).where(model.folder_id == folder_id, model.name == res["name"])).scalars().first()
            elif res["scope"] == "shared":
                identical = store.with_content(org_id, res["sha256"]) if res.get("sha256") else []
                same = session.get(model, identical[0]["id"]) if identical else session.execute(
                    select(model).where(model.org_id == org_id, model.name == res["name"])).scalars().first()
            if same is not None:
                entry["existing"] = {"id": same.id, "name": same.name, "where": folder_path(session, same.folder_id)}
                same_sha = store.fingerprint(same.id)
                entry["status"] = "identical" if same_sha == res.get("sha256") else "differs"
            elif res["scope"] == "project" and res.get("sha256"):
                elsewhere = store.with_content(org_id, res["sha256"])
                if elsewhere:
                    first = elsewhere[0]
                    entry["existing"] = {"id": first["id"], "name": first["name"], "where": folder_path(session, first["folder_id"])}
                    entry["status"] = "identical_elsewhere"
                else:
                    entry["status"] = "new"
            else:
                entry["status"] = "new"
            if not entry["included"] and entry["status"] in ("new", "identical_elsewhere") and res["scope"] == "shared":
                entry["status"] = "missing"
            if not entry["included"] and entry["status"] == "differs":
                entry["choices"], entry["default"] = ["use_existing"], "use_existing"
            else:
                entry["choices"] = _choices(res["scope"], entry["status"])
                entry["default"] = {
                    ("project", "differs"): "overwrite", ("shared", "differs"): "use_existing",
                    ("project", "new"): "create", ("shared", "new"): "create_shared",
                    ("project", "identical_elsewhere"): "copy_into_project",
                }.get((res["scope"], entry["status"]))
            resources.append(entry)

        templates = []
        for t in m.get("templates", []):
            entry = {"key": t["key"], "name": t["name"], "template_ext": t["template_ext"], "code": t.get("code"), "folder": t.get("folder") or "", "match": None}
            match = None
            if t.get("code"):
                match = session.execute(select(db.ReportRow).where(db.ReportRow.code == t["code"])).scalar_one_or_none()
                if match is not None and (match.org_id != org_id or (target is not None and match.folder_id not in paths) or target is None):
                    entry["code_note"] = f'The code "{t["code"]}" belongs to another template here ({match.name}) -- this one is imported without it'
                    match = None
            if match is None and target is not None:
                folder_id = by_path.get(t.get("folder") or "")
                if folder_id:
                    match = session.execute(select(db.ReportRow).where(db.ReportRow.folder_id == folder_id, db.ReportRow.name == t["name"])).scalars().first()
            if match is not None:
                entry["match"] = {"id": match.report_id, "name": match.name, "version": match.version}
                entry["status"], entry["choices"], entry["default"] = "exists", ["update", "keep_both", "skip"], "update"
            else:
                entry["status"], entry["choices"], entry["default"] = "new", ["create", "skip"], "create"
            templates.append(entry)

        can_terms = context.is_superuser or context.has_permission("protected_terms:manage")
        term_sets = []
        for ts in m.get("term_sets", []):
            same = session.execute(select(db.ProtectedTermSet).where(db.ProtectedTermSet.org_id == org_id, db.ProtectedTermSet.name == ts["name"])).scalars().first()
            entry = {"key": ts["key"], "name": ts["name"], "terms": len(ts.get("terms") or [])}
            if same is None:
                entry["status"], entry["choices"] = "new", ["create", "skip"] if can_terms else ["skip"]
            elif sorted(same.terms or []) == sorted(ts.get("terms") or []) and sorted(same.exclude_terms or []) == sorted(ts.get("exclude_terms") or []):
                entry["status"], entry["choices"], entry["existing"] = "identical", [], {"id": same.id, "name": same.name}
            else:
                entry["status"], entry["existing"] = "differs", {"id": same.id, "name": same.name}
                entry["choices"] = ["use_existing", "overwrite", "keep_both"] if can_terms else ["use_existing"]
            entry["default"] = entry["choices"][0] if entry["choices"] else None
            term_sets.append(entry)

        can_fonts = context.is_superuser or context.has_permission("font:manage")
        fonts = []
        for f in m.get("fonts", []):
            entry = {"key": f["key"], "family": f["family"], "subfamily": f["subfamily"]}
            if session.scalar(select(db.FontResource.id).where(db.FontResource.sha256 == f["sha256"])):
                entry["status"], entry["choices"] = "identical", []
            elif (clash := session.execute(select(db.FontResource).where(db.FontResource.family_key == f["family"].lower(),
                                                                         db.FontResource.subfamily_key == f["subfamily"].lower())).scalar_one_or_none()):
                entry["status"], entry["existing"] = "differs", {"id": clash.id, "version": clash.version}
                entry["choices"] = ["use_existing", "replace"] if can_fonts else ["use_existing"]
            else:
                entry["status"], entry["choices"] = "new", (["install", "skip"] if can_fonts else ["skip"])
                if not can_fonts:
                    entry["note"] = "Adding a font needs the font:manage permission -- ask someone who has it, or add it under Resources > Fonts"
            entry["default"] = entry["choices"][0] if entry["choices"] else None
            fonts.append(entry)

        refs = m.get("references") or {}
        warnings = []
        names = {r.name for r in session.execute(select(db.DataConnection).where(db.DataConnection.org_id == org_id)).scalars()}
        for name in refs.get("connections", []):
            if name not in names:
                warnings.append(f'Connection "{name}" doesn\'t exist here -- create it under Manage > Connections before running these templates')
        secrets = {r.name for r in session.execute(select(db.Secret).where(db.Secret.org_id == org_id)).scalars()}
        for name in refs.get("secrets", []):
            if name not in secrets:
                warnings.append(f'Secret "{name}" doesn\'t exist here -- secrets never travel in a package; create it under Manage > Secrets')
        datasets = {r.name for r in session.execute(select(db.Dataset).where(db.Dataset.org_id == org_id)).scalars()}
        for name in refs.get("datasets", []):
            if name not in datasets:
                warnings.append(f'Dataset "{name}" doesn\'t exist here -- the templates built on it won\'t run until it does')
        for r in resources:
            if r["status"] == "missing":
                warnings.append(f'{r["kind"].capitalize()} "{r["name"]}" was left out of the package and isn\'t here -- {", ".join(r["used_by"]) or "templates"} will need it')
        return {
            "project": {"name": target.name if target else m["project"]["name"], "existing_id": target.id if target else None,
                        "exported_at": m.get("exported_at"), "exported_by": m.get("exported_by")},
            "contains": m.get("contains", {}),
            "templates": templates, "resources": resources, "term_sets": term_sets, "fonts": fonts, "warnings": warnings,
        }


# --- keeping a package between the preview and the import --------------------------------------------------------


def stash(data: bytes, org_id: str, user_key: str, into: str | None) -> str:
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for old in IMPORT_DIR.glob("*.json"):  # leftovers from previews nobody applied
        try:
            if now - json.loads(old.read_text())["at"] > TOKEN_SECONDS:
                old.unlink(missing_ok=True)
                old.with_suffix(".zip").unlink(missing_ok=True)
        except (OSError, ValueError, KeyError):
            continue
    token = uuid.uuid4().hex
    (IMPORT_DIR / f"{token}.zip").write_bytes(data)
    (IMPORT_DIR / f"{token}.json").write_text(json.dumps({"at": now, "org_id": org_id, "user": user_key, "into": into}))
    return token


def unstash(token: str, user_key: str) -> tuple[bytes, dict]:
    if not _TOKEN_RE.match(token or ""):
        raise LookupError("import")
    meta_path = IMPORT_DIR / f"{token}.json"
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, ValueError) as exc:
        raise LookupError("import") from exc
    if meta.get("user") != user_key or time.time() - meta["at"] > TOKEN_SECONDS:
        raise LookupError("import")
    return (IMPORT_DIR / f"{token}.zip").read_bytes(), meta


def discard(token: str) -> None:
    for suffix in (".zip", ".json"):
        (IMPORT_DIR / f"{token}{suffix}").unlink(missing_ok=True)


# --- applying an import ------------------------------------------------------------------------------------------


class _Undo:
    """What an import created or changed, so a failure half-way leaves the server as it was."""

    def __init__(self):
        self.steps: list = []

    def add(self, fn) -> None:
        self.steps.append(fn)

    def run(self) -> None:
        for fn in reversed(self.steps):
            try:
                fn()
            except Exception:  # noqa: BLE001 -- undo as much as can be undone
                pass


def _valid_template(content: bytes, ext: str, name: str) -> None:
    if ext == "html":
        from .html_template import parse_html_template

        try:
            parsed = parse_html_template(content.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise ProjectError(f'Template "{name}" isn\'t valid UTF-8 HTML') from exc
        if parsed.errors:
            raise ProjectError(f'Template "{name}": {parsed.errors[0].message}')
    elif not report_store.is_valid_office_file(content, ext):
        raise ProjectError(f'Template "{name}" isn\'t a valid .{ext} file')


def apply(pkg: Package, org_id: str, *, into: str | None, decisions: dict[str, str], context, actor) -> dict:
    """Import `pkg` with the deployer's `decisions` ({item key: choice}; an item not named takes its default).
    Everything is checked first; then created; existing things are changed last, and only if all else worked."""
    m = pkg.manifest
    preview = plan(pkg, org_id, into=into, context=context)

    def choice(item: dict) -> str | None:
        picked = decisions.get(item["key"], item.get("default"))
        if item.get("choices") and picked not in item["choices"]:
            raise ProjectError(f'"{picked}" isn\'t a choice for {item.get("name") or item.get("family")}')
        return picked if item.get("choices") else None

    # Check every file before writing anything.
    for t in m.get("templates", []):
        _valid_template(pkg.read(t["file"]), t["template_ext"], t["name"])
        for h in t.get("history") or []:
            _valid_template(pkg.read(h["file"]), h["template_ext"], f'{t["name"]} v{h["version"]}')
    for r in m.get("resources", []):
        content = pkg.read(r.get("file"))
        if content is not None:
            if r["kind"] == "image":
                image_store.probe_image(content)
            else:
                stylesheet_store._compiled(content, _style_format(r))  # it must compile here too
            if r.get("sha256") and hashlib.sha256(content).hexdigest() != r["sha256"]:
                raise ProjectError(f'{r["name"]} in the package is damaged (its fingerprint doesn\'t match)')
    picks = {i["key"]: choice(i) for group in ("resources", "templates", "term_sets", "fonts") for i in preview[group]}

    user_id = context.user.id if context.user else None
    undo, later = _Undo(), []
    summary = {"created": [], "updated": [], "linked": [], "skipped": [], "warnings": list(preview["warnings"])}
    try:
        # The project and its folders.
        with db.SessionLocal() as session:
            if into:
                root = project_row(session, into)
            else:
                root = db.Folder(id=db._gen_id(), org_id=org_id, parent_folder_id=None, name=m["project"]["name"],
                                 description=m["project"].get("description"), created_by=user_id, created_at=_now(), updated_at=_now(), is_project=True)
                session.add(root)
                session.commit()
                root_id = root.id
                undo.add(lambda: _delete_folder(root_id))
                summary["created"].append(f'Project "{root.name}"')
            paths = _tree(session, root)
            by_path = {p: fid for fid, p in paths.items()}
            for path in sorted(m.get("folders", []), key=lambda p: p.count("/")):
                if path in by_path:
                    continue
                parent = by_path[path.rsplit("/", 1)[0]] if "/" in path else root.id
                row = db.Folder(id=db._gen_id(), org_id=org_id, parent_folder_id=parent, name=path.rsplit("/", 1)[-1],
                                created_by=user_id, created_at=_now(), updated_at=_now())
                session.add(row)
                session.commit()
                by_path[path] = row.id
                undo.add(lambda fid=row.id: _delete_folder(fid))
            root_id, root_name = root.id, root.name

        # Resources: link, create, or (later) overwrite.
        ids: dict[str, str | None] = {}
        manifest_res = {r["key"]: r for r in m.get("resources", [])}
        for item in preview["resources"]:
            r, pick = manifest_res[item["key"]], picks[item["key"]]
            store = image_store if r["kind"] == "image" else stylesheet_store
            existing = (item.get("existing") or {}).get("id")
            if item["status"] == "identical" or pick in ("use_existing", "link"):
                ids[r["key"]] = existing
                summary["linked"].append(f'{r["name"]} (already here)')
                continue
            if item["status"] == "missing":
                ids[r["key"]] = None
                continue
            content = pkg.read(r["file"])
            if pick == "overwrite":
                ids[r["key"]] = existing
                later.append(("resource", store, existing, content, r["name"], _style_format(r) if r["kind"] == "stylesheet" else None))
                continue
            folder = by_path.get(r.get("folder") or "", root_id) if r["scope"] == "project" else None
            if pick in ("keep_both", "create_in_project", "copy_into_project"):
                folder = by_path.get(r.get("folder") or "", root_id) if r["scope"] == "project" else root_id
            if r["kind"] == "image":
                created = image_store.create_image(name=r["name"], content=content, org_id=org_id, folder_id=folder, created_by=user_id)
            else:
                created = stylesheet_store.create_stylesheet(name=r["name"], content=content, org_id=org_id, folder_id=folder,
                                                             created_by=user_id, source_format=_style_format(r))
            ids[r["key"]] = created["id"]
            undo.add(lambda s=store, i=created["id"]: (s.delete_image if s is image_store else s.delete_stylesheet)(i))
            summary["created"].append(f'{r["kind"].capitalize()} "{r["name"]}"' + (" (shared)" if folder is None else ""))

        # Protected term sets.
        term_ids: dict[str, str | None] = {}
        manifest_terms = {t["key"]: t for t in m.get("term_sets", [])}
        for item in preview["term_sets"]:
            ts, pick = manifest_terms[item["key"]], picks[item["key"]]
            existing = (item.get("existing") or {}).get("id")
            if item["status"] == "identical" or pick == "use_existing":
                term_ids[ts["key"]] = existing
            elif pick in ("create", "keep_both"):
                name = ts["name"] if pick == "create" else f'{ts["name"]} (imported)'
                row = term_store.create_set(org_id, name, ts.get("description"), ts.get("terms") or [], ts.get("exclude_terms") or [], user_id)
                term_ids[ts["key"]] = row["id"]
                undo.add(lambda i=row["id"]: term_store.delete_set(i))
                summary["created"].append(f'Protected terms "{name}"')
            elif pick == "overwrite":
                term_ids[ts["key"]] = existing
                later.append(("terms", existing, ts))
            else:
                term_ids[ts["key"]] = None
                summary["skipped"].append(f'Protected terms "{ts["name"]}"')

        # Fonts (server-wide).
        manifest_fonts = {f["key"]: f for f in m.get("fonts", [])}
        for item in preview["fonts"]:
            f, pick = manifest_fonts[item["key"]], picks[item["key"]]
            if pick == "install":
                font_id = _install_font(pkg.read(f["file"]), f, user_id)
                undo.add(lambda i=font_id: _remove_font(i))
                summary["created"].append(f'Font {f["family"]} {f["subfamily"]}')
            elif pick == "replace":
                later.append(("font", item["existing"]["id"], f))
            elif item["status"] == "new":
                summary["skipped"].append(f'Font {f["family"]} {f["subfamily"]} (not added)')

        # Templates.
        manifest_tpl = {t["key"]: t for t in m.get("templates", [])}
        for item in preview["templates"]:
            t, pick = manifest_tpl[item["key"]], picks[item["key"]]
            if pick == "skip":
                summary["skipped"].append(f'Template "{t["name"]}"')
                continue
            folder_id = by_path.get(t.get("folder") or "", root_id)
            bindings = {name: {"kind": b["kind"], "id": ids.get(b.get("ref"))} for name, b in (t.get("resource_bindings") or {}).items() if ids.get(b.get("ref"))}
            sample = _from_refs(t.get("sample_context"), ids) if t.get("sample_context") is not None else None
            source = _from_refs(t.get("data_source"), ids) if t.get("data_source") is not None else None
            terms_cfg = {"set_ids": [term_ids[k] for k in t.get("protected_terms", {}).get("set_refs", []) if term_ids.get(k)],
                         "terms": t.get("protected_terms", {}).get("terms", []), "exclude_terms": t.get("protected_terms", {}).get("exclude_terms", [])}
            note = f'Imported from project package ({m.get("exported_at", "")[:10]})' + (f': {t["note"]}' if t.get("note") else "")
            if pick == "update":
                report_id = item["match"]["id"]
                report_store.replace_report_file(report_id, pkg.read(t["file"]), t["template_ext"], actor=actor, note=note)
                with db.SessionLocal() as session:
                    row = session.get(db.ReportRow, report_id)
                    row.resource_bindings = bindings or row.resource_bindings
                    row.description = t.get("description")
                    if m.get("contains", {}).get("data_sources"):
                        row.parameters, row.data_source, row.sample_context = t.get("parameters"), source, sample
                    row.protected_terms_config = terms_cfg if (terms_cfg["set_ids"] or terms_cfg["terms"] or terms_cfg["exclude_terms"]) else None
                    session.commit()
                summary["updated"].append(f'Template "{t["name"]}" (new version)')
                continue
            code = t.get("code") if pick == "create" and not item.get("code_note") else None
            name = t["name"] if pick == "create" else f'{t["name"]} (imported)'
            history = t.get("history") or []
            first = history[0] if history else None
            created = report_store.create_report(
                name, pkg.read(first["file"] if first else t["file"]), first["template_ext"] if first else t["template_ext"],
                t.get("description"), org_id, bindings or None, code=code, folder_id=folder_id, actor=actor,
                note=(first.get("note") if first else note), is_draft=bool(t.get("is_draft")),
                sample_context=sample, parameters=t.get("parameters"), data_source=source,
            )
            report_id = created["report_id"]
            undo.add(lambda i=report_id: report_store.delete_report(i))
            for h in history[1:]:
                report_store.replace_report_file(report_id, pkg.read(h["file"]), h["template_ext"], actor=actor, note=h.get("note"), version_label=h.get("label"))
            if first:
                report_store.replace_report_file(report_id, pkg.read(t["file"]), t["template_ext"], actor=actor, note=note, version_label=t.get("version_label"))
            if terms_cfg["set_ids"] or terms_cfg["terms"] or terms_cfg["exclude_terms"]:
                report_store.update_protected_terms_config(report_id, terms_cfg)
            if t.get("is_public"):
                report_store.update_report_meta(report_id, is_public=True)
            summary["created"].append(f'Template "{name}"' + (f" ({len(history) + 1} versions)" if history else ""))
            if item.get("code_note"):
                summary["warnings"].append(item["code_note"])

        # Last: changes to things that already existed.
        for step in later:
            if step[0] == "resource":
                _, store, rid, content, rname, fmt = step
                if store is image_store:
                    old = image_store.get_image_bytes(rid)
                    image_store.replace_image_content(rid, content)
                    undo.add(lambda i=rid, o=old: image_store.replace_image_content(i, o))
                else:
                    old, old_fmt = stylesheet_store.get_stylesheet_source(rid)
                    stylesheet_store.replace_stylesheet_content(rid, content, fmt)
                    undo.add(lambda i=rid, o=old, f=old_fmt: stylesheet_store.replace_stylesheet_content(i, o, f))
                summary["updated"].append(f'"{rname}" (overwritten -- every template using it changes)')
            elif step[0] == "terms":
                _, tid, ts = step
                before = term_store.get_set(tid)
                term_store.update_set(tid, before["name"], ts.get("description"), ts.get("terms") or [], ts.get("exclude_terms") or [])
                undo.add(lambda i=tid, b=before: term_store.update_set(i, b["name"], b.get("description"), b.get("terms") or [], b.get("exclude_terms") or []))
                summary["updated"].append(f'Protected terms "{before["name"]}" (overwritten)')
            elif step[0] == "font":
                _, old_id, f = step
                _remove_font(old_id)
                _install_font(pkg.read(f["file"]), f, user_id)
                summary["updated"].append(f'Font {f["family"]} {f["subfamily"]} (replaced)')
    except Exception:
        undo.run()
        raise
    summary["project"] = {"id": root_id, "name": root_name}
    return summary


def _style_format(r: dict) -> str:
    """A packaged stylesheet's format -- css, scss, sass or less (a package from before formats: css)."""
    fmt = r.get("ext") or "css"
    return fmt if fmt in ("css", "scss", "sass", "less") else "css"


def _delete_folder(folder_id: str) -> None:
    with db.SessionLocal() as session:
        row = session.get(db.Folder, folder_id)
        if row is not None:
            session.delete(row)
            session.commit()


def _install_font(data: bytes, f: dict, user_id: str | None) -> str:
    from .routers.fonts import install_font

    return install_font(data, filename=f.get("filename") or f'{f["family"]}.ttf', note=f.get("note") or "Imported with a project", user_id=user_id)["id"]


def _remove_font(font_id: str) -> None:
    from .routers.fonts import remove_font

    remove_font(font_id)


__all__ = ["contents", "export", "plan", "apply", "Package", "ProjectError", "NotAProject", "stash", "unstash", "discard", "shutil"]
