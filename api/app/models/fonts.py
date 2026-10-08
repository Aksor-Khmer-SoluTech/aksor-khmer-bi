from __future__ import annotations

from pydantic import BaseModel, Field


class FontOut(BaseModel):
    """A font uploaded under Resources > Fonts -- installed for the whole server."""

    id: str
    family: str = Field(..., description="What a template names this font by")
    subfamily: str
    full_name: str
    postscript_name: str
    version: str
    weight: int
    italic: bool
    glyph_count: int
    khmer_coverage: float = Field(..., description="Percent of the assigned Khmer-block code points the font has glyphs for")
    latin_coverage: float = Field(..., description="Percent of printable ASCII the font has glyphs for")
    has_layout_tables: bool = Field(..., description="Has GSUB and GPOS -- what Khmer needs to place vowels and subscripts")
    copyright: str
    license: str
    license_url: str
    embedding: str
    note: str
    filename: str
    file_ext: str
    sha256: str
    size_bytes: int
    created_at: str
    used_by: list[str] = Field(default_factory=list, description="Names of the templates that name this family")
    warnings: list[str] = Field(default_factory=list, description="Things worth knowing, e.g. missing Khmer coverage")
    shadows_installed: bool = Field(False, description="The server already has a font with this family name")


class InstalledFont(BaseModel):
    family: str
    source: str = Field(..., description="'uploaded' (Resources > Fonts) or 'system' (installed on the server)")


class TemplateFont(BaseModel):
    name: str
    status: str = Field(..., description="uploaded | installed | substituted | missing")
    resolved_to: str | None = Field(None, description="The font actually used when the named one is substituted")
