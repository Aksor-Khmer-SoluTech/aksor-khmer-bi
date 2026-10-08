"""What is inside a font file -- read with fontTools, which is pure Python (a malformed font can't corrupt this
process's memory the way a native parser's bug could).

Used when a font is uploaded (Resources > Fonts) so a developer can *verify* it before any template depends on it:
the family and style a template must name, the version, how much of Khmer and Latin it really covers, whether it can
shape Khmer at all (the layout tables), and what its license says. Reading is read-only and size-bounded by the
caller; nothing here writes a file.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

from fontTools.ttLib import TTFont, TTLibError

# What counts as "all of Khmer" and "basic Latin": the assigned code points of the Khmer block and printable ASCII.
KHMER_CODEPOINTS = (
    list(range(0x1780, 0x17DE))  # letters, vowels, signs (U+17DE-17DF are unassigned)
    + list(range(0x17E0, 0x17EA))  # digits
    + list(range(0x17F0, 0x17FA))  # lunar-date digits
)
LATIN_CODEPOINTS = list(range(0x20, 0x7F))

_SIGNATURES = {b"\x00\x01\x00\x00": "ttf", b"true": "ttf", b"OTTO": "otf"}

EMBEDDING = {
    0x0000: "Installable embedding allowed",
    0x0002: "Restricted license embedding (the license forbids embedding it in documents)",
    0x0004: "Preview & print embedding allowed",
    0x0008: "Editable embedding allowed",
}


class FontError(ValueError):
    """The file isn't a usable font; the message is safe to show."""


@dataclass
class FontInfo:
    family: str
    subfamily: str
    full_name: str
    postscript_name: str
    version: str
    weight: int
    italic: bool
    glyph_count: int
    file_ext: str
    copyright: str
    license: str
    license_url: str
    fs_type: int
    embedding: str
    has_layout_tables: bool
    khmer_coverage: float
    latin_coverage: float
    warnings: list[str] = field(default_factory=list)


def sniff(head: bytes) -> str:
    """'ttf' or 'otf' from the first four bytes -- the file's own signature, never its name."""
    kind = _SIGNATURES.get(head[:4])
    if kind is None:
        if head[:4] == b"ttcf":
            raise FontError("A font collection (.ttc) isn't supported -- upload each font as its own .ttf or .otf")
        if head[:4] in (b"wOFF", b"wOF2"):
            raise FontError("A web font (.woff/.woff2) isn't supported -- upload the .ttf or .otf it came from")
        raise FontError("That isn't a TrueType (.ttf) or OpenType (.otf) font")
    return kind


def _clip(text: str | None, limit: int) -> str:
    return " ".join((text or "").split())[:limit]


def _coverage(cmap: dict[int, str], wanted: list[int]) -> float:
    return round(100.0 * sum(1 for cp in wanted if cp in cmap) / len(wanted), 1)


def warnings_for(khmer_coverage: float, has_layout_tables: bool, embedding_restricted: bool) -> list[str]:
    """Things worth knowing about a font before a template depends on it -- derived from what is stored, so the
    list shows the same on upload and on every later look."""
    out: list[str] = []
    if embedding_restricted:
        out.append("The font's license forbids embedding it in documents, but PDFs embed the fonts they use.")
    if khmer_coverage == 0:
        out.append("It has no Khmer glyphs, so it can't draw Khmer text.")
    elif khmer_coverage < 70:
        out.append(f"It covers only {khmer_coverage}% of the Khmer block, so some Khmer text will show missing-glyph boxes.")
    if khmer_coverage > 0 and not has_layout_tables:
        out.append("It has no GSUB/GPOS layout tables, which Khmer needs to place vowels and subscripts correctly.")
    return out


def inspect(data: bytes) -> FontInfo:
    """Read a font's identity, coverage and license. Raises FontError for anything that isn't a usable font."""
    ext = sniff(data)
    try:
        font = TTFont(io.BytesIO(data), lazy=False)
        names = font["name"]
        cmap = font.getBestCmap() or {}
        head, maxp = font["head"], font["maxp"]
        os2 = font["OS/2"] if "OS/2" in font else None
        family = names.getDebugName(16) or names.getDebugName(1)
        subfamily = names.getDebugName(17) or names.getDebugName(2) or "Regular"
        full_name = names.getDebugName(4) or f"{family} {subfamily}"
        postscript = names.getDebugName(6) or ""
    except (TTLibError, KeyError, AttributeError, struct_error, EOFError, ValueError, AssertionError) as exc:
        raise FontError("That font file is damaged or incomplete") from exc
    if not family:
        raise FontError("That font has no family name, so a template couldn't ask for it")
    if not cmap:
        raise FontError("That font has no character map, so it can't draw any text")

    weight = int(getattr(os2, "usWeightClass", 400) or 400)
    selection = int(getattr(os2, "fsSelection", 0) or 0)
    italic = bool(selection & 0x01) or (("post" in font) and bool(getattr(font["post"], "italicAngle", 0)))
    fs_type = int(getattr(os2, "fsType", 0) or 0)
    # The lowest set restriction bit decides: 0x0002 forbids embedding; otherwise a preview/print or editable
    # permission, else installable.
    if fs_type & 0x0002:
        embedding = EMBEDDING[0x0002]
    elif fs_type & 0x0008:
        embedding = EMBEDDING[0x0008]
    elif fs_type & 0x0004:
        embedding = EMBEDDING[0x0004]
    else:
        embedding = EMBEDDING[0x0000]

    khmer, latin = _coverage(cmap, KHMER_CODEPOINTS), _coverage(cmap, LATIN_CODEPOINTS)
    layout = "GSUB" in font and "GPOS" in font
    warnings = warnings_for(khmer, layout, bool(fs_type & 0x0002))

    return FontInfo(
        family=_clip(family, 100),
        subfamily=_clip(subfamily, 60),
        full_name=_clip(full_name, 160),
        postscript_name=_clip(postscript, 80),
        version=_clip(names.getDebugName(5), 80),
        weight=weight,
        italic=italic,
        glyph_count=int(maxp.numGlyphs),
        file_ext=ext,
        copyright=_clip(names.getDebugName(0), 300),
        license=_clip(names.getDebugName(13), 500),
        license_url=_clip(names.getDebugName(14), 300),
        fs_type=fs_type,
        embedding=embedding,
        has_layout_tables=layout,
        khmer_coverage=khmer,
        latin_coverage=latin,
        warnings=warnings,
    )


# Blocks shown in the font viewer, so a developer can see *which* characters a font has before relying on it.
BLOCKS = (
    ("Khmer", 0x1780, 0x17FF),
    ("Khmer symbols", 0x19E0, 0x19FF),
    ("Basic Latin", 0x0020, 0x007E),
    ("Latin-1 supplement", 0x00A0, 0x00FF),
    ("Punctuation and joiners", 0x2000, 0x206F),
    ("Currency", 0x20A0, 0x20BF),
)


def coverage_blocks(data: bytes) -> list[dict]:
    """For each block of interest, the code points the font has a glyph for. Unassigned code points inside a block
    are left out of both lists, so "missing" only ever means a character that exists and the font lacks."""
    import unicodedata

    try:
        cmap = TTFont(io.BytesIO(data), lazy=False).getBestCmap() or {}
    except (TTLibError, KeyError, struct_error, EOFError, ValueError, AssertionError) as exc:
        raise FontError("That font file is damaged or incomplete") from exc
    blocks = []
    for name, start, end in BLOCKS:
        assigned = [cp for cp in range(start, end + 1) if unicodedata.category(chr(cp)) != "Cn"]
        blocks.append(
            {
                "name": name,
                "start": start,
                "end": end,
                "present": [cp for cp in assigned if cp in cmap],
                "missing": [cp for cp in assigned if cp not in cmap],
            }
        )
    return blocks


try:  # fontTools raises struct.error on truncated tables
    from struct import error as struct_error
except ImportError:  # pragma: no cover
    struct_error = ValueError
