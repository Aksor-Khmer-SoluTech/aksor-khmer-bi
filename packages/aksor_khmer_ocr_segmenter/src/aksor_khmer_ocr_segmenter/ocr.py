"""Khmer OCR via Tesseract.

Requires the system `tesseract` binary plus the Khmer trained-data file
(`khm.traineddata`) — see scripts/setup_env.sh for how those were installed
for this project. Both are open source (Apache 2.0).
"""
from __future__ import annotations

from pathlib import Path

import pytesseract
from PIL import Image


def ocr_image(
    image_path: str | Path,
    lang: str = "khm",
    psm: int = 6,
) -> str:
    """Run Tesseract OCR on an image and return the raw recognized text.

    `psm` (page segmentation mode) 6 = "assume a single uniform block of
    text", a reasonable default for a scanned paragraph or form field. Use
    7 for a single line (e.g. a cropped placeholder field).
    """
    image = Image.open(image_path)
    config = f"--psm {psm}"
    text = pytesseract.image_to_string(image, lang=lang, config=config)
    return text.strip()
