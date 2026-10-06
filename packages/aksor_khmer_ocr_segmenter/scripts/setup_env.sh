#!/usr/bin/env bash
# One-time environment setup for macOS + Homebrew.
# Installs: Tesseract OCR core, the Khmer trained-data file (fast/small
# variant, ~1.4MB — NOT the multi-GB `tesseract-lang` bundle), and ICU4C
# (needed by PyICU for dictionary-based Khmer word segmentation).
set -euo pipefail

echo "==> Installing tesseract + icu4c via Homebrew"
brew install tesseract icu4c

TESSDATA_DIR="$(brew --prefix)/share/tessdata"
echo "==> Downloading khm.traineddata into $TESSDATA_DIR"
mkdir -p "$TESSDATA_DIR"
curl -fL -o "$TESSDATA_DIR/khm.traineddata" \
    https://github.com/tesseract-ocr/tessdata_fast/raw/main/khm.traineddata

echo "==> Installing Python dependencies (PyICU built against icu4c)"
ICU_PREFIX="$(brew --prefix icu4c)"
PATH="$ICU_PREFIX/bin:$PATH" \
PKG_CONFIG_PATH="$ICU_PREFIX/lib/pkgconfig" \
    pip install -r "$(dirname "$0")/../requirements.txt"

echo "==> Verifying"
tesseract --list-langs
python3 -c "import icu; print('PyICU OK, ICU version', icu.ICU_VERSION)"

echo "Done."
