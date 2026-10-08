"""Fonts -- Resources > Fonts: add a font to the whole server without redeploying anything.

A font added here is used by the next render of every template that names its family: LibreOffice (docx), WeasyPrint
(html) and the chart renderer all pick it up from data/font_resources (see app/font_store.py and doc_engine/fonts.py).
It is server-wide, not per organization, so adding and removing need `font:manage` (system administrators only by
default); seeing the list, and checking a font before relying on it, needs that or `report:manage`.

What an upload is checked for: the file's own signature (a real .ttf/.otf, not just a name), a size cap, and a full
read with fontTools -- pure Python, so a malformed font can't harm this process. The response says what is in the font
(family and style a template must name, version, Khmer/Latin coverage, layout tables, license) and warns about the
things that make output wrong later: a font that can't draw Khmer, or whose license forbids embedding.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .. import audit, db, font_catalog, font_info, font_store, report_store
from ..auth import get_current_user, require_permission
from ..models import FontOut, InstalledFont
from ..rbac import AuthContext

router = APIRouter(prefix="/api/v1/fonts", tags=["fonts"])

_manage = require_permission("font:manage")


def _require_view(context: AuthContext = Depends(get_current_user)) -> AuthContext:
    if context.has_permission("font:manage") or context.has_permission("report:manage"):
        return context
    raise HTTPException(status_code=403, detail="Missing required permission: font:manage or report:manage")


def _templates_by_family() -> dict[str, list[str]]:
    """{lower-case family: [names of the templates that name it]} across every report on the server."""
    used: dict[str, list[str]] = {}
    for meta in report_store.list_reports():
        try:
            path = report_store.get_template_path(meta["report_id"])
        except report_store.ReportNotFoundError:
            continue
        for name in font_catalog.fonts_named_by(path, meta["template_ext"]):
            used.setdefault(name.lower(), []).append(meta["name"])
    return used


def _out(row: db.FontResource, used: dict[str, list[str]], *, warnings: list[str] | None = None, shadows: bool = False) -> FontOut:
    return FontOut(
        id=row.id, family=row.family, subfamily=row.subfamily, full_name=row.full_name, postscript_name=row.postscript_name,
        version=row.version, weight=row.weight, italic=row.italic, glyph_count=row.glyph_count,
        khmer_coverage=row.khmer_coverage, latin_coverage=row.latin_coverage, has_layout_tables=row.has_layout_tables,
        copyright=row.copyright, license=row.license, license_url=row.license_url, embedding=row.embedding, note=row.note,
        filename=row.filename, file_ext=row.file_ext, sha256=row.sha256, size_bytes=row.size_bytes, created_at=row.created_at,
        used_by=sorted(set(used.get(row.family_key, []))),
        warnings=(warnings if warnings is not None else font_info.warnings_for(
            row.khmer_coverage, row.has_layout_tables, row.embedding.startswith("Restricted")
        )),
        shadows_installed=shadows,
    )


def _get(session, font_id: str) -> db.FontResource:
    row = session.get(db.FontResource, font_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Font not found")
    return row


@router.get("", summary="List the fonts added under Resources > Fonts", response_model=list[FontOut])
def list_fonts(_: AuthContext = Depends(_require_view)) -> list[FontOut]:
    used = _templates_by_family()
    with db.SessionLocal() as session:
        rows = session.scalars(select(db.FontResource).order_by(db.FontResource.family_key, db.FontResource.weight))
        return [_out(row, used) for row in rows]


@router.get("/installed", summary="Every font family the server can draw with", response_model=list[InstalledFont])
def list_installed(_: AuthContext = Depends(_require_view)) -> list[InstalledFont]:
    with db.SessionLocal() as session:
        uploaded = {row.family_key: row.family for row in session.scalars(select(db.FontResource))}
    families = [InstalledFont(family=name, source="uploaded") for name in sorted(uploaded.values(), key=str.lower)]
    system = font_catalog.system_families()
    families += [InstalledFont(family=name, source="system") for key, name in sorted(system.items()) if key not in uploaded]
    return families


@router.post("", summary="Add a font (.ttf or .otf) for the whole server", response_model=FontOut)
def upload_font(
    request: Request,
    file: UploadFile = File(..., description="A TrueType (.ttf) or OpenType (.otf) font"),
    note: str = Form("", description="Optional: where it came from, who approved its license"),
    context: AuthContext = Depends(_manage),
) -> FontOut:
    try:
        data = font_store.read_upload(file.file)
        info = font_info.inspect(data)
    except font_info.FontError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    digest = font_store.sha256_of(data)
    shadows = info.family.lower() in font_catalog.system_families()
    warnings = list(info.warnings)
    if shadows:
        warnings.append(
            f"The server already has a font named {info.family!r}. Which of the two a render uses is up to the "
            "operating system's font matching, so check the result -- or give this font its own family name."
        )

    with db.SessionLocal() as session:
        if session.scalar(select(db.FontResource.id).where(db.FontResource.sha256 == digest)):
            raise HTTPException(status_code=409, detail="That exact font file has already been added")
        clash = session.scalar(
            select(db.FontResource).where(
                db.FontResource.family_key == info.family.lower(), db.FontResource.subfamily_key == info.subfamily.lower()
            )
        )
        if clash is not None:
            raise HTTPException(
                status_code=409,
                detail=f"{info.family} {info.subfamily} is already there (version {clash.version or 'unknown'}). Remove it "
                "first if you mean to replace it -- two files can't both be that font.",
            )
        row = db.FontResource(
            family=info.family, family_key=info.family.lower(), subfamily=info.subfamily, subfamily_key=info.subfamily.lower(),
            full_name=info.full_name, postscript_name=info.postscript_name, version=info.version, weight=info.weight,
            italic=info.italic, glyph_count=info.glyph_count, khmer_coverage=info.khmer_coverage,
            latin_coverage=info.latin_coverage, has_layout_tables=info.has_layout_tables, copyright=info.copyright,
            license=info.license, license_url=info.license_url, embedding=info.embedding, note=(note or "").strip()[:300],
            filename=(file.filename or f"font.{info.file_ext}")[:200], file_ext=info.file_ext, sha256=digest,
            size_bytes=len(data), created_at=datetime.now(timezone.utc).isoformat(),
            created_by=context.user.id if context.user else None,
        )
        session.add(row)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail="That font is already there") from exc
        font_store.save(row.id, row.file_ext, data)
        try:
            session.commit()
        except Exception:
            session.rollback()
            font_store.remove_file(row.id, row.file_ext)
            raise
        font_catalog.forget()
        audit.record(
            audit.Actor.of(context, request), "font.upload", "font", row.id, label=f"{row.family} {row.subfamily}",
            summary=f"Added font {row.family} {row.subfamily} (version {row.version or 'unknown'})",
            details={"filename": row.filename, "sha256": row.sha256, "size_bytes": row.size_bytes, "khmer_coverage": row.khmer_coverage},
        )
        return _out(row, {}, warnings=warnings, shadows=shadows)


@router.get("/{font_id}", summary="One font, with the templates that use it", response_model=FontOut)
def get_font(font_id: str, _: AuthContext = Depends(_require_view)) -> FontOut:
    with db.SessionLocal() as session:
        return _out(_get(session, font_id), _templates_by_family())


@router.get("/{font_id}/file", summary="The font file itself (for previewing it in the browser)")
def download_font(font_id: str, _: AuthContext = Depends(_require_view)) -> FileResponse:
    with db.SessionLocal() as session:
        row = _get(session, font_id)
        path, filename, ext = font_store.path_for(row.id, row.file_ext), row.filename, row.file_ext
    if not path.exists():
        raise HTTPException(status_code=404, detail="The font's file is missing from the server")
    return FileResponse(path, media_type="font/otf" if ext == "otf" else "font/ttf", filename=filename)


@router.get("/{font_id}/coverage", summary="Which characters the font has, block by block")
def font_coverage(font_id: str, _: AuthContext = Depends(_require_view)) -> list[dict]:
    with db.SessionLocal() as session:
        row = _get(session, font_id)
        path = font_store.path_for(row.id, row.file_ext)
    try:
        return font_info.coverage_blocks(path.read_bytes())
    except OSError:
        raise HTTPException(status_code=404, detail="The font's file is missing from the server")
    except font_info.FontError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{font_id}", status_code=204, summary="Remove a font")
def delete_font(
    font_id: str,
    request: Request,
    force: bool = Query(False, description="Remove it even though templates name it (they will render in a substitute font)"),
    context: AuthContext = Depends(_manage),
) -> None:
    with db.SessionLocal() as session:
        row = _get(session, font_id)
        users = sorted(set(_templates_by_family().get(row.family_key, [])))
        if users and not force:
            raise HTTPException(
                status_code=409,
                detail=f"{row.family} is named by {', '.join(users[:5])}{' and more' if len(users) > 5 else ''} -- they would render "
                "in a substitute font. Remove it anyway with force=true.",
            )
        label, ext = f"{row.family} {row.subfamily}", row.file_ext
        session.delete(row)
        session.commit()
    font_store.remove_file(font_id, ext)
    font_catalog.forget()
    audit.record(
        audit.Actor.of(context, request), "font.delete", "font", font_id, label=label,
        summary=f"Removed font {label}" + (f" (named by {len(users)} template(s))" if users else ""),
    )
