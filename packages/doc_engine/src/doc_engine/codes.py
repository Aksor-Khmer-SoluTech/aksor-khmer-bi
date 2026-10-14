"""QR codes and barcodes drawn at render time, from a value -- see docs/building-a-report.md's "Barcodes and QR
codes". One drawing module for all three template kinds; each engine only decides how the picture gets in:

* a template function, the same in every kind of template -- `{{ qrcode(invoice.no) }}`,
  `{{ barcode(invoice.no, "ean13") }}` -- so a plain value from any data source (a SQL column, a REST field) works;
* or, in the data instead of the template (docx and xlsx), a spec like a chart's:
  `{"qr": "…", "width_mm": 25}` / `{"barcode": "code128", "value": "…", "width_mm": 50}`.

Word and Excel get a PNG -- a barcode drawn for the width it's placed at, every bar whole pixels (barcode_png
says why); HTML gets an SVG `data:` URI, which stays sharp at any size in the PDF.

The value is encoded exactly as given, with one exception: the zero-width spaces Khmer segmentation inserts
(segmentation.py runs over every string before any engine sees it) are taken out again -- they are line-break hints
for the page, not part of the value, and a QR holding them would scan back as something else.
"""
from __future__ import annotations

import base64
import io
import re
from typing import Any

QR_LEVELS = ("L", "M", "Q", "H")
BARCODE_TYPES = ("code128", "code39", "ean13")
DEFAULT_QR_WIDTH_MM = 25
DEFAULT_BARCODE_WIDTH_MM = 50
_SEGMENTATION_MARKS = re.compile("[​]")
_MAX_LENGTH = 2000


class CodeError(ValueError):
    """A value that can't be drawn as the code asked for -- letters in an EAN-13, a wrong check digit, Khmer in a
    Code 39. Raised while rendering, so the render fails with this message instead of printing a code nobody can
    scan."""


def _positive(n: Any) -> bool:
    return isinstance(n, (int, float)) and not isinstance(n, bool) and n > 0


def _value(value: Any) -> str:
    if value is None or value == "":
        raise CodeError("A QR code or barcode needs a value -- this one is empty")
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise CodeError(f"A QR code or barcode is drawn from text or a number, not {type(value).__name__}")
    text = _SEGMENTATION_MARKS.sub("", str(value))
    if len(text) > _MAX_LENGTH:
        raise CodeError(f"That value is {len(text):,} characters -- too long for a code (at most {_MAX_LENGTH:,})")
    return text


def barcode_type(kind: Any) -> str:
    """"ean-13", "EAN13", "Code 39", "code_128"… as one of BARCODE_TYPES."""
    name = re.sub(r"[\s_-]", "", str(kind or "")).lower()
    if name not in BARCODE_TYPES:
        raise CodeError(f"Unknown barcode type {kind!r} -- use code128, code39 or ean13")
    return name


def qr_level(level: Any) -> str:
    name = str(level or "M").upper()
    if name not in QR_LEVELS:
        raise CodeError(f"A QR code's error correction is L, M, Q or H, not {level!r}")
    return name


# --- QR ----------------------------------------------------------------------------------------------------------------


def _qr(value: Any, level: Any):
    import qrcode
    from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q

    levels = {"L": ERROR_CORRECT_L, "M": ERROR_CORRECT_M, "Q": ERROR_CORRECT_Q, "H": ERROR_CORRECT_H}
    code = qrcode.QRCode(error_correction=levels[qr_level(level)], border=4, box_size=10)
    code.add_data(_value(value).encode("utf-8"))  # bytes: UTF-8 for Khmer, as phone scanners expect
    try:
        code.make(fit=True)
    except Exception as exc:  # qrcode's DataOverflowError
        raise CodeError("That value is too long for a QR code -- shorten it or use a lower error correction") from exc
    return code


def qr_png(value: Any, level: Any = "M") -> bytes:
    out = io.BytesIO()
    _qr(value, level).make_image().save(out, format="PNG")
    return out.getvalue()


def qr_svg(value: Any, level: Any = "M") -> bytes:
    from qrcode.image.svg import SvgPathImage

    out = io.BytesIO()
    _qr(value, level).make_image(image_factory=SvgPathImage).save(out)
    return out.getvalue()


# --- barcodes ----------------------------------------------------------------------------------------------------------


def _ean13(text: str) -> str:
    """12 digits get their check digit; 13 must already have the right one."""
    if not text.isdigit() or len(text) not in (12, 13):
        raise CodeError(f"An EAN-13 is 12 digits (the check digit is added) or 13 digits -- not {text!r}")
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(text[:12]))
    check = str((10 - total % 10) % 10)
    if len(text) == 13 and text[12] != check:
        raise CodeError(f"{text!r} isn't a valid EAN-13: its check digit should be {check}")
    return text[:12] + check


def _barcode(value: Any, kind: Any, writer):
    import barcode
    from barcode.errors import BarcodeError

    name, text = barcode_type(kind), _value(value)
    if name == "ean13":
        text = _ean13(text)
    elif name == "code39":
        text = text.upper()  # Code 39 has capitals only; lower case reads the same once printed
        bad = sorted({c for c in text if not re.match(r"[0-9A-Z \-.$/+%]", c)})
        if bad:
            raise CodeError(f"Code 39 can't hold {''.join(bad)!r} -- only A-Z, 0-9, space and - . $ / + %")
    elif any(ord(c) > 127 for c in text):
        raise CodeError("Code 128 holds plain ASCII only -- put Khmer or other text in a QR code instead")
    options = {"add_checksum": False} if name == "code39" else {}
    try:
        return barcode.get(name, text, writer=writer, options=options)
    except (BarcodeError, KeyError, ValueError) as exc:
        raise CodeError(f"{text!r} can't be drawn as {name}: {exc}") from exc


def _writer_options(text: bool) -> dict:
    # Bars 0.33 mm wide and 15 mm tall before scaling: a common print size that scanners read comfortably.
    return {"module_width": 0.33, "module_height": 15.0, "quiet_zone": 3.0, "write_text": bool(text), "font_size": 8, "text_distance": 3.0}


_PPI = 300  # LibreOffice's PDF export resamples pictures above this; a barcode at or below it is left as drawn
_QUIET_MODULES = 10


def barcode_png(value: Any, kind: Any = "code128", text: bool = False, width_mm: float | None = None, height_mm: float | None = None) -> bytes:
    """The barcode drawn for the width it will be placed at: every bar a whole number of pixels, at no more than
    300 pixels per inch there -- so nothing downstream resamples it and makes some bars a pixel thinner than others,
    which is what stops a printed barcode scanning (QR codes shrug that off; barcodes don't). `height_mm`, with
    `width_mm`, sets its proportions (text included), so a picture placed at that width is that tall."""
    from PIL import Image, ImageDraw, ImageFont

    code = _barcode(value, kind, None)
    bars = code.build()[0]
    modules = len(bars) + 2 * _QUIET_MODULES
    target_px = (width_mm or DEFAULT_BARCODE_WIDTH_MM) / 25.4 * _PPI
    k = max(1, int(target_px // modules))  # pixels per module
    width = modules * k
    label = code.get_fullcode() if text else ""
    if height_mm:
        if not (_positive(height_mm) and height_mm <= 200):
            raise CodeError(f"A barcode's height_mm is a number of millimetres above 0, not {height_mm!r}")
        height = max(round(width * float(height_mm) / float(width_mm or DEFAULT_BARCODE_WIDTH_MM)), 12)
        font_px = max(round(height * 0.18), 10) if label else 0
        bar_height = height - (font_px + round(font_px * 0.6) if label else 0)
    else:
        bar_height = max(round(width * 0.28), 60)
        font_px = max(round(bar_height * 0.22), 14)
        height = bar_height + (font_px + round(font_px * 0.6) if label else 0)
    image = Image.new("1", (width, height), 1)
    draw = ImageDraw.Draw(image)
    x = _QUIET_MODULES * k
    for bit in bars:
        if bit == "1":
            draw.rectangle([x, 0, x + k - 1, bar_height - 1], fill=0)
        x += k
    if label:
        import barcode as _pkg
        from pathlib import Path

        font = ImageFont.truetype(str(Path(_pkg.__file__).with_name("fonts") / "DejaVuSansMono.ttf"), font_px)
        draw.text((width / 2, bar_height + round(font_px * 0.3)), label, font=font, fill=0, anchor="ma")
    out = io.BytesIO()
    image.save(out, format="PNG", dpi=(_PPI, _PPI))
    return out.getvalue()


def barcode_svg(value: Any, kind: Any = "code128", text: bool = False) -> bytes:
    from barcode.writer import SVGWriter

    out = io.BytesIO()
    _barcode(value, kind, SVGWriter()).write(out, options=_writer_options(text))
    return _with_view_box(out.getvalue())


def _with_view_box(svg: bytes) -> bytes:
    """python-barcode's SVG has a size in mm but no viewBox, so a browser shows it at that size whatever CSS asks
    for. A viewBox in the same units (1 mm = 96/25.4 user units) lets `width: 40mm` scale it, as WeasyPrint does.
    And it fills the box it's given (preserveAspectRatio="none"): a barcode stretched wider just has wider bars, all
    in proportion, and still scans -- where keeping its shape in a wide 190x30 box would shrink it to a third."""
    text = svg.decode("utf-8")
    size = re.search(r'<svg\b[^>]*\bwidth="([\d.]+)mm"[^>]*\bheight="([\d.]+)mm"', text)
    if not size or "viewBox" in text[: size.end()]:
        return svg
    w, h = (float(v) * 96 / 25.4 for v in size.groups())
    return text.replace("<svg ", f'<svg viewBox="0 0 {w:.3f} {h:.3f}" preserveAspectRatio="none" ', 1).encode("utf-8")


# --- for the engines ---------------------------------------------------------------------------------------------------


def svg_data_uri(svg: bytes) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode("ascii")


_QR_KEYS = {"qr", "level", "width_mm"}
_BARCODE_KEYS = {"barcode", "value", "width_mm", "height_mm", "text"}


def is_code_spec(value: object) -> bool:
    """A QR code or barcode asked for in the data: {"qr": "…"} or {"barcode": "code128", "value": "…"} -- and nothing
    else in the dict, so an ordinary row that happens to have a "qr" or "barcode" column ({"barcode": "885…",
    "name": …}) stays data."""
    if not isinstance(value, dict):
        return False
    if "qr" in value and set(value) <= _QR_KEYS:
        return not isinstance(value["qr"], (dict, list))
    if "barcode" in value and "value" in value and set(value) <= _BARCODE_KEYS:
        try:
            barcode_type(value["barcode"])
        except CodeError:
            return False
        return True
    return False


def spec_png(spec: dict) -> tuple[bytes, float]:
    """(PNG, width in mm) for a spec from the data."""
    if "qr" in spec:
        return qr_png(spec["qr"], spec.get("level", "M")), float(spec.get("width_mm") or DEFAULT_QR_WIDTH_MM)
    width = float(spec.get("width_mm") or DEFAULT_BARCODE_WIDTH_MM)
    return barcode_png(spec["value"], spec["barcode"], bool(spec.get("text", False)), width, spec.get("height_mm")), width


FUNCTION_NAMES = ("qrcode", "barcode")


class _CallableStr(str):
    def __call__(self, *args, **kwargs):
        return self._draw(*args, **kwargs)


class _CallableInt(int):
    def __call__(self, *args, **kwargs):
        return self._draw(*args, **kwargs)


class _CallableFloat(float):
    def __call__(self, *args, **kwargs):
        return self._draw(*args, **kwargs)


def with_functions(context: dict, functions: dict) -> dict:
    """`context` with the code functions added. A label template is likely to have its own `barcode` field and want
    to draw it -- `{{ barcode(barcode, "ean13") }}` -- so a text or number field of the same name is kept as a value
    that prints as itself (`{{ barcode }}`) *and* draws the code when called. A field that is a list or an object
    stays as it was (it can't be both)."""
    out = dict(context)
    for name, draw in functions.items():
        value = out.get(name)
        if name not in out:
            out[name] = draw
            continue
        for kind, wrapper in ((bool, None), (str, _CallableStr), (int, _CallableInt), (float, _CallableFloat)):
            if isinstance(value, kind):
                if wrapper is not None:
                    wrapped = wrapper(value)
                    wrapped._draw = draw
                    out[name] = wrapped
                break
    return out
