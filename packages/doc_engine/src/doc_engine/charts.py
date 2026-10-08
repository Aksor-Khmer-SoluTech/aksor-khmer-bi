"""Render chart specs (see docs/building-a-report.md's Charts section) to
PNG bytes via matplotlib, for embedding as a static image into generated
documents — see engines/libreoffice_engine.py for where the PNG becomes
an actual InlineImage in the docx.

This is document-embedded static charts, one rendered picture per spec —
not an interactive dashboard/BI layer (see docs/why-aksor-khmer-bi.md for
that explicit scope boundary; adding this didn't change it).

Registered with this project's own bundled Khmer font so chart
titles/labels/legends render correctly, same as every other text path in
this project — verified empirically (tests/test_charts.py renders a real
chart with Khmer labels and checks the PNG is non-trivial and the right
size; visual correctness was additionally eyeballed once by hand during
development, the same way every other rendering claim in this repo was).

Chart spec shape (a plain dict, JSON-compatible so it can travel in a
render request's context):
    {
        "chart": "bar" | "line" | "pie",
        "title": "optional string",
        "labels": ["category 1", "category 2", ...],
        "series": [{"name": "optional", "values": [1, 2, ...]}, ...],
        "width_mm": 150,   # optional, default below
        "height_mm": 90,   # optional, default below
    }
`pie` only ever uses series[0]; `bar`/`line` support multiple series
(grouped bars / multiple lines), each becoming one legend entry.
"""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")  # headless — no display server; safe in a container/CLI

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt

from . import fonts
from .config import TEMPLATES_DIR

CHART_TYPES = {"bar", "line", "pie"}
DEFAULT_WIDTH_MM = 150
DEFAULT_HEIGHT_MM = 90

_FONT_PATH = TEMPLATES_DIR / "fonts" / "KhmerOSSiemreap.ttf"
_khmer_font_name: str | None = None


def _font_family(requested: object = None) -> list[str]:
    """KhmerOSSiemreap.ttf has no Latin glyphs at all (verified directly
    against its cmap — A-Z/a-z are simply absent, only Khmer + digits are
    covered). Word/LibreOffice paper over this invisibly via OS-level
    font-substitution fallback, but matplotlib does not substitute
    automatically for a font you hand it directly — it renders a missing
    glyph. Matplotlib 3.6+'s font.family DOES accept a fallback list,
    though, so any Latin in a title/label/legend (a date, "Q1", a plain
    English word) falls through to DejaVu Sans (bundled with matplotlib,
    always available) instead of coming out as a blank box — confirmed
    empirically with mixed Khmer+Latin text before relying on it here.
    """
    global _khmer_font_name
    if _khmer_font_name is None:
        fm.fontManager.addfont(str(_FONT_PATH))
        _khmer_font_name = fm.FontProperties(fname=str(_FONT_PATH)).get_name()
    # A chart spec may name another font ("font": "Noto Sans Khmer") -- one installed on the server or added under
    # Resources > Fonts. Tried first; the Khmer font and DejaVu stay behind it for any glyph it lacks.
    fonts.register_with_matplotlib()
    family = fonts.safe_family(requested)
    if family:
        try:
            fm.findfont(fm.FontProperties(family=family), fallback_to_default=False)
            return [family, _khmer_font_name, "DejaVu Sans"]
        except ValueError:
            pass  # not installed: fall through to the default pair rather than failing the whole report
    return [_khmer_font_name, "DejaVu Sans"]


def is_chart_spec(value: object) -> bool:
    """True for a dict shaped like a chart spec — used both to detect
    what to render (engines/libreoffice_engine.py) and what NOT to
    Khmer-segment (segmentation.py): a chart's structural keys ("chart",
    "width_mm", ...) aren't free text, and its actual text (title,
    labels) is short/non-wrapping, so ICU segmentation serves no purpose
    there and would corrupt the "chart" type discriminator itself if
    applied blindly.
    """
    return isinstance(value, dict) and value.get("chart") in CHART_TYPES


def render_chart_png(spec: dict) -> bytes:
    chart_type = spec["chart"]
    if chart_type not in CHART_TYPES:
        raise ValueError(f"Unknown chart type: {chart_type!r}")

    labels = spec.get("labels", [])
    series = spec.get("series", [])
    title = spec.get("title")
    width_mm = spec.get("width_mm", DEFAULT_WIDTH_MM)
    height_mm = spec.get("height_mm", DEFAULT_HEIGHT_MM)

    # Scoped to this call (rc_context), not a global plt.rcParams mutation
    # — avoids leaking font state across concurrent render calls.
    with matplotlib.rc_context({"font.family": _font_family(spec.get("font"))}):
        fig, ax = plt.subplots(figsize=(width_mm / 25.4, height_mm / 25.4))

        if chart_type == "bar":
            _draw_bar(ax, labels, series)
        elif chart_type == "line":
            _draw_line(ax, labels, series)
        else:
            _draw_pie(ax, labels, series)

        if title:
            ax.set_title(title, fontsize=14)
        if chart_type != "pie" and len(series) > 1:
            ax.legend()

        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150)
        plt.close(fig)
        return buf.getvalue()


def _draw_bar(ax, labels, series) -> None:
    positions = list(range(len(labels)))
    n = max(len(series), 1)
    width = 0.8 / n
    for i, s in enumerate(series):
        offset = (i - (n - 1) / 2) * width
        ax.bar([p + offset for p in positions], s["values"], width=width, label=s.get("name"))
    ax.set_xticks(positions)
    ax.set_xticklabels(labels)


def _draw_line(ax, labels, series) -> None:
    for s in series:
        ax.plot(labels, s["values"], marker="o", label=s.get("name"))


def _draw_pie(ax, labels, series) -> None:
    values = series[0]["values"] if series else []
    ax.pie(values, labels=labels, autopct="%1.0f%%")
