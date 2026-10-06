# aksor-khmer-ocr-segmenter

Open-source OCR + word segmentation for Khmer text, built to solve one
specific problem: **a placeholder value ends up longer or unspaced, and the
document layout engine has nowhere to break the line.**

Khmer is normally written without spaces between words. Some renderers
(WeasyPrint/Pango, browsers) have no dictionary to find word boundaries in
that unspaced text, so a long unspaced string just overflows instead of
wrapping. Word/LibreOffice's Writer engine gets this right because it uses
ICU's dictionary-based break iterator internally.

This project exposes that same mechanism as a standalone, reusable step:

1. **OCR** (`tesseract`, Apache 2.0, with the `khm` trained-data file) — for
   when the source text comes from a scanned image or screenshot rather
   than digital text.
2. **Segmentation** (`PyICU`, wrapping ICU4C's dictionary-based Khmer word
   `BreakIterator` — the same open-source library LibreOffice/ICU-based
   tools use) — finds the correct word boundaries in unspaced text.
3. **Break insertion** — re-joins the segmented words with either a normal
   space (visible) or a zero-width space `U+200B` (invisible — keeps the
   traditional unspaced Khmer look while still giving any layout engine a
   legal place to break a line or stretch for justify).

## Why ICU instead of a hand-built dictionary

An early approach for this kind of problem is a maximum-matching segmenter
against a plain word list. ICU ships a maintained, linguist-curated Khmer
dictionary and boundary implementation instead — no word list to source,
license, or keep up to date. Verified against real unspaced sentences
(see `tests/test_segmenter.py`).

## Project layout

```
aksor_khmer_ocr_segmenter/
├── pyproject.toml            # packaging + the `aksor-khmer-ocr-segment` CLI entry point
├── requirements.txt
├── scripts/
│   └── setup_env.sh          # one-time macOS/Homebrew environment setup
├── src/aksor_khmer_ocr_segmenter/
│   ├── ocr.py                # Tesseract wrapper (image -> raw text)
│   ├── segmenter.py          # ICU word BreakIterator (text -> words / break-inserted text)
│   ├── pipeline.py           # OCR -> segment, or text -> segment
│   ├── cli.py                # `aksor-khmer-ocr-segment` command-line tool
│   └── protected_terms/      # known ICU mis-splits, one module per category, + loader.py
│                              # for injecting extra terms from a text file (see below)
├── tests/
│   ├── test_segmenter.py
│   ├── test_pipeline.py
│   └── test_protected_terms_loader.py
└── samples/                  # drop test images here; protected_terms_example.txt
                               # shows the extra-terms file format
```

## Setup

```bash
cd aksor_khmer_ocr_segmenter
./scripts/setup_env.sh        # installs tesseract, khm.traineddata, icu4c, PyICU, etc.
pip install -e .              # install this package + the CLI entry point
```

The setup script pulls only the Khmer trained-data file (~1.4MB) from
[tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast), not the
multi-GB `tesseract-lang` bundle.

## Usage

### CLI

```bash
# Digital text that's unspaced or came out longer than a form field expects
aksor-khmer-ocr-segment --text "កម្ពុជាជាប្រទេសមួយស្ថិតនៅតំបន់អាស៊ីអាគ្នេយ៍"

# OCR a scanned/screenshotted field, then segment the result
aksor-khmer-ocr-segment --image samples/scan.png

# Use a visible space instead of the default invisible ZWSP (easier to eyeball while debugging)
aksor-khmer-ocr-segment --text "..." --visible-space
```

### Library

```python
from aksor_khmer_ocr_segmenter import process_text, process_image

# Already-digital text (e.g. a placeholder value about to be rendered)
corrected = process_text(long_unspaced_khmer_string)

# Scanned image
corrected = process_image("scan.png")
```

## Known-mis-split names/loanwords (protected terms)

ICU's Khmer dictionary is built for native vocabulary, so it sometimes
splits transliterated names and loanwords mid-syllable (e.g. `ឥណ្ឌូនេស៊ី`
"Indonesia" → `ឥណ្ឌូ`/`នេ`/`ស៊ី`). `aksor_khmer_ocr_segmenter.protected_terms`
carries a curated list of concretely observed cases across countries,
Cambodian place names, personal names, surnames, science/tech loanwords,
brands, and legal vocabulary — `segment()` re-merges these automatically.
See `docs/khmer-line-breaking.md` in the parent repo for the full writeup,
and `docs/protected-terms-guide.md` for the standard procedure for adding a
new term, the classification rubric, and the full catalog by category
(106 terms across 8 files as of this writing).

### Adding your own terms without editing this package

Set `AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE` to a `.txt` file (one term per line,
`#` comments allowed) or a `.json` file (an array of strings, or
`{"terms": [...]}`) — see `samples/protected_terms_example.txt` /
`.json` — to have it merged in automatically:

```bash
export AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE=/path/to/your_terms.txt
```

Or scope it to one call/run instead:

```bash
aksor-khmer-ocr-segment --text "..." --protected-terms-file your_terms.txt
```

```python
process_text(text, extra_terms_file="your_terms.txt")
```

Have several term sources (per-customer, per-dataset)? Point at a
directory instead — every `*.txt` file directly inside it gets merged in:

```bash
export AKSOR_KHMER_OCR_PROTECTED_TERMS_DIR=/path/to/terms.d
# or: --protected-terms-dir terms.d / extra_terms_dir="terms.d"
```

### Excluding a built-in (or injected) term

The inverse mechanism: `AKSOR_KHMER_OCR_EXCLUDED_TERMS_FILE` (same `.txt`/`.json`
formats — see `samples/excluded_terms_example.txt`) removes listed terms
from the merge set, reverting to ICU's original behavior for just those
terms:

```bash
export AKSOR_KHMER_OCR_EXCLUDED_TERMS_FILE=/path/to/your_exclusions.txt
# or scoped to one call:
aksor-khmer-ocr-segment --text "..." --exclude-terms-file your_exclusions.txt
process_text(text, exclude_terms_file="your_exclusions.txt")
```

Useful if a built-in term is actually wrong for your data, without having
to fork or edit this package. If a term is both injected and excluded in
the same call, exclusion wins. Same directory form as injection:
`AKSOR_KHMER_OCR_EXCLUDED_TERMS_DIR` / `--exclude-terms-dir` /
`exclude_terms_dir=`.

## Fitting this into the document pipeline

This project pairs with the `docxtpl` / WeasyPrint templating work in the
parent directory. Run any placeholder value through `process_text()` before
handing it to the template context, so a value that's longer or more
"run-together" than expected still gives the renderer real break points:

```python
from aksor_khmer_ocr_segmenter import process_text

data = {
    "taxpayer_name": process_text(raw_name),
    "address": process_text(raw_address),
    ...
}
```

Since LibreOffice already does dictionary-based Khmer line breaking on its
own (see the parent project's stress test), inserting ZWSP is mostly
insurance for engines that don't (WeasyPrint) or for guaranteeing evenly
distributed justify stretch when a field has very few natural spaces.
