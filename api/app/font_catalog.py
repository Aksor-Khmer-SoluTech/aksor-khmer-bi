"""Which fonts the server can draw with, and which fonts a template asks for.

Two questions a developer asks before trusting a template:

* *What is installed?* -- the families the operating system knows (fontconfig, i.e. what LibreOffice and WeasyPrint
  see) plus the ones added under Resources > Fonts.
* *What does this template name, and will it be found?* -- read from the template file itself (a docx names fonts in
  its XML, an html in its CSS, an xlsx in its styles), then looked up: **uploaded**, **installed**, or **missing**
  -- in which case the renderer quietly substitutes another font, and the layout changes.

Everything is read-only and cached briefly; the font list is refreshed after an upload or delete.
"""
from __future__ import annotations

import functools
import io
import re
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path

_lock = threading.Lock()
_system_cache: tuple[float, dict[str, str]] | None = None
_TTL = 60.0

_GENERIC = {
    "serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif", "ui-sans-serif",
    "ui-monospace", "ui-rounded", "emoji", "math", "fangsong", "inherit", "initial", "unset", "revert",
}


def forget() -> None:
    """Drop the cached lists (after a font was added or removed)."""
    global _system_cache
    with _lock:
        _system_cache = None


def system_families() -> dict[str, str]:
    """{lower-case family: family} the operating system offers, via fontconfig (`fc-list`). Falls back to
    matplotlib's font list on a machine without fontconfig (a developer's laptop)."""
    global _system_cache
    with _lock:
        if _system_cache and time.monotonic() - _system_cache[0] < _TTL:
            return _system_cache[1]
    found: dict[str, str] = {}
    if shutil.which("fc-list"):
        try:
            out = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True, timeout=20, check=True).stdout
            for line in out.splitlines():
                for name in line.split(","):
                    name = name.strip()
                    if name:
                        found.setdefault(name.lower(), name)
        except (subprocess.SubprocessError, OSError):
            found = {}
    if not found:
        try:
            import matplotlib.font_manager as fm

            for entry in fm.fontManager.ttflist:
                found.setdefault(entry.name.lower(), entry.name)
        except Exception:  # noqa: BLE001 -- a missing list must never break a page
            pass
    with _lock:
        _system_cache = (time.monotonic(), found)
    return found


# Names the renderers map to an installed, metric-compatible font (same advance widths, so the layout holds). Anything
# else that isn't installed is drawn in whatever default the renderer picks -- which is *not* something fontconfig can
# be asked about reliably (LibreOffice has its own replacement table), so it is reported as missing, not guessed.
_ALIASES = {
    "arial": "Liberation Sans",
    "helvetica": "Liberation Sans",
    "times new roman": "Liberation Serif",
    "times": "Liberation Serif",
    "courier new": "Liberation Mono",
    "courier": "Liberation Mono",
    "symbol": "OpenSymbol",
}


def substitute_for(family: str) -> str | None:
    """The installed, metric-compatible font that stands in for `family` ("Times New Roman" -> "Liberation Serif"),
    or None when there is no such stand-in."""
    target = _ALIASES.get(family.lower())
    return target if target and target.lower() in system_families() else None


def status_of(name: str, uploaded_families: set[str]) -> dict:
    """{"name", "status": uploaded | installed | substituted | missing, "resolved_to"} for a font a template names."""
    key = name.lower()
    if key in {f.lower() for f in uploaded_families}:
        return {"name": name, "status": "uploaded", "resolved_to": name}
    if key in system_families():
        return {"name": name, "status": "installed", "resolved_to": name}
    replacement = substitute_for(name)
    if replacement:
        return {"name": name, "status": "substituted", "resolved_to": replacement}
    return {"name": name, "status": "missing", "resolved_to": None}


# --- what a template names ---------------------------------------------------------------------------------------

# Only inside <w:rFonts ...>: the same attribute names also appear on <w:lang w:eastAsia="ja-JP"/>, which is a language.
_DOCX_RFONTS = re.compile(r"<w:rFonts\b([^>]*)>")
_DOCX_FONT_ATTR = re.compile(r'w:(?:ascii|hAnsi|cs|eastAsia)="([^"]{1,100})"')
_DOCX_THEME_ATTR = re.compile(r'w:(?:ascii|hAnsi|cs|eastAsia)Theme="')
_THEME_FONT = re.compile(r'<a:(?:latin|cs)\s+typeface="([^"]{1,100})"')
_XLSX_FONT = re.compile(r'<name\s+val="([^"]{1,100})"')
_CSS_FAMILY = re.compile(r"font-family\s*:\s*([^;}{>]+)", re.IGNORECASE)
_FONT_SHORTHAND = re.compile(r"font\s*:\s*[^;}{>]*?(?:\d[\w.%]*(?:/[\w.%]+)?)\s+([^;}{>]+)", re.IGNORECASE)


def _clean(names) -> list[str]:
    seen: dict[str, str] = {}
    for raw in names:
        name = raw.strip().strip("'\"").strip()
        if name and name.lower() not in _GENERIC and not name.lower().startswith(("+", "var(")):
            seen.setdefault(name.lower(), name)
    return list(seen.values())


def _docx_fonts(archive: zipfile.ZipFile) -> list[str]:
    names: list[str] = []
    theme_used = False
    for part in archive.namelist():
        if part.startswith("word/") and part.endswith(".xml") and part.count("/") == 1 and "fontTable" not in part:
            xml = archive.read(part).decode("utf-8", errors="ignore")
            for attrs in _DOCX_RFONTS.findall(xml):
                names += _DOCX_FONT_ATTR.findall(attrs)
                theme_used = theme_used or bool(_DOCX_THEME_ATTR.search(attrs))
    if theme_used and "word/theme/theme1.xml" in archive.namelist():
        theme = archive.read("word/theme/theme1.xml").decode("utf-8", errors="ignore")
        minor = re.search(r"<a:minorFont>(.*?)</a:minorFont>", theme, re.S)
        major = re.search(r"<a:majorFont>(.*?)</a:majorFont>", theme, re.S)
        for block in (minor, major):
            if block:
                names += _THEME_FONT.findall(block.group(1))
    return _clean(names)


def _xlsx_fonts(archive: zipfile.ZipFile) -> list[str]:
    if "xl/styles.xml" not in archive.namelist():
        return []
    xml = archive.read("xl/styles.xml").decode("utf-8", errors="ignore")
    fonts = re.search(r"<fonts[^>]*>(.*?)</fonts>", xml, re.S)
    return _clean(_XLSX_FONT.findall(fonts.group(1) if fonts else ""))


def _html_fonts(text: str) -> list[str]:
    names: list[str] = []
    for declaration in _CSS_FAMILY.findall(text):
        names += declaration.split(",")
    for declaration in _FONT_SHORTHAND.findall(text):
        names += declaration.split(",")
    return _clean(names)


@functools.lru_cache(maxsize=512)
def _fonts_in_file(path: str, mtime_ns: int, ext: str) -> tuple[str, ...]:
    try:
        if ext == "html":
            return tuple(_html_fonts(Path(path).read_text(encoding="utf-8", errors="ignore")))
        with zipfile.ZipFile(io.BytesIO(Path(path).read_bytes())) as archive:
            return tuple(_docx_fonts(archive) if ext == "docx" else _xlsx_fonts(archive) if ext == "xlsx" else [])
    except (OSError, zipfile.BadZipFile, KeyError):
        return ()


def fonts_named_by(template_path: Path, ext: str) -> list[str]:
    """The font families a template file names, in the order found."""
    try:
        return list(_fonts_in_file(str(template_path), template_path.stat().st_mtime_ns, ext))
    except OSError:
        return []
