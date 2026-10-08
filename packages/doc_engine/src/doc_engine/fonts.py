"""Extra fonts a deployment adds at runtime (the portal's Resources > Fonts), made visible to each rendering path
without restarting anything.

The folders come from DOC_ENGINE_FONT_DIRS (os.pathsep separated; the API sets it to data/font_resources). Every
`.ttf` / `.otf` in them is a font, and the three ways documents get their fonts each need their own hand-off:

* **docx -> pdf/png (LibreOffice).** `soffice` is started afresh for every conversion with its own throw-away profile,
  and LibreOffice loads whatever is in `<profile>/user/fonts` at start-up. `install_into_profile` links the fonts there,
  so a font uploaded a second ago is used by the next render. (Pointing fontconfig at the folder did not work with
  LibreOffice; the profile folder did -- tried both.)
* **html -> pdf/png (WeasyPrint).** The template can only load `data:` URLs, so `font_face_css` returns `@font-face`
  rules whose source is the font itself as a `data:` URL -- for just the families the HTML mentions.
* **charts (matplotlib).** `register_with_matplotlib` adds the files to matplotlib's font list.

Nothing here reads a database: the library only ever sees files. A font is identified by the family name inside the
file (name ID 16, else 1), which is what a template names it by.
"""
from __future__ import annotations

import base64
import logging
import os
import re
from pathlib import Path

from fontTools.ttLib import TTFont, TTLibError

_log = logging.getLogger(__name__)

ENV_VAR = "DOC_ENGINE_FONT_DIRS"
FONT_SUFFIXES = (".ttf", ".otf")

# (path, mtime_ns) -> family. Reading a font's name table is cheap but not free, and renders are frequent.
_family_cache: dict[tuple[str, int], str | None] = {}
_registered_with_matplotlib: set[str] = set()


def font_dirs() -> list[Path]:
    return [Path(p) for p in os.environ.get(ENV_VAR, "").split(os.pathsep) if p.strip()]


def family_name(path: Path) -> str | None:
    """The family a template names this font by (typographic family if present, else the legacy one)."""
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return None
    if key not in _family_cache:
        family = None
        try:
            with TTFont(str(path), lazy=True, fontNumber=0) as font:
                names = font["name"]
                family = names.getDebugName(16) or names.getDebugName(1)
        except (TTLibError, OSError, KeyError, ValueError) as exc:
            _log.warning("Ignoring unreadable font %s: %s", path, exc)
        _family_cache[key] = family
    return _family_cache[key]


def installed() -> list[tuple[Path, str]]:
    """(file, family) for every readable font file in the configured folders, in a stable order."""
    found: list[tuple[Path, str]] = []
    for folder in font_dirs():
        try:
            files = sorted(p for p in folder.iterdir() if p.suffix.lower() in FONT_SUFFIXES and p.is_file())
        except OSError:
            continue
        for path in files:
            family = family_name(path)
            if family:
                found.append((path, family))
    return found


def install_into_profile(profile_dir: Path) -> int:
    """Link every extra font into a LibreOffice profile's `user/fonts` folder. Returns how many."""
    fonts = installed()
    if not fonts:
        return 0
    target = profile_dir / "user" / "fonts"
    target.mkdir(parents=True, exist_ok=True)
    for path, _family in fonts:
        link = target / path.name
        try:
            link.symlink_to(path.resolve())
        except OSError:
            # A filesystem without symlinks (or a read-only target): copy instead.
            link.write_bytes(path.read_bytes())
    return len(fonts)


def _css_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def font_face_css(html: str) -> str:
    """`@font-face` rules (font bytes inlined as `data:` URLs) for the extra fonts whose family the HTML mentions."""
    wanted = html.lower()
    rules: list[str] = []
    for path, family in installed():
        if family.lower() not in wanted:
            continue
        mime = "font/otf" if path.suffix.lower() == ".otf" else "font/ttf"
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        rules.append(f"@font-face{{font-family:{_css_string(family)};src:url(data:{mime};base64,{data})}}")
    return "\n".join(rules)


def register_with_matplotlib() -> None:
    import matplotlib.font_manager as fm

    for path, _family in installed():
        key = str(path)
        if key not in _registered_with_matplotlib:
            try:
                fm.fontManager.addfont(key)
            except (OSError, RuntimeError, ValueError) as exc:
                _log.warning("matplotlib couldn't load font %s: %s", path, exc)
            _registered_with_matplotlib.add(key)


_FAMILY_RE = re.compile(r"^[^\x00-\x1f\"\\]{1,100}$")


def safe_family(name: object) -> str | None:
    """A font family name from a template or a chart spec, if it is plain text of reasonable size."""
    return name.strip() if isinstance(name, str) and _FAMILY_RE.match(name.strip() or "\x00") else None
