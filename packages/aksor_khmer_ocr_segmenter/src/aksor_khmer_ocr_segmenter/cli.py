#!/usr/bin/env python3
"""Command-line entry point.

Examples:
    aksor-khmer-ocr-segment --text "កម្ពុជាជាប្រទេសមួយស្ថិតនៅតំបន់អាស៊ីអាគ្នេយ៍"
    aksor-khmer-ocr-segment --image scan.png --visible-space
    aksor-khmer-ocr-segment --image scan.png --psm 7
    aksor-khmer-ocr-segment --text "..." --protected-terms-file my_terms.txt
    aksor-khmer-ocr-segment --text "..." --exclude-terms-file my_exclusions.json
    aksor-khmer-ocr-segment --text "..." --protected-terms-dir ./terms.d
    aksor-khmer-ocr-segment --text "..." --exclude-terms-dir ./exclude.d

`--protected-terms-file` / `--exclude-terms-file` each accept a `.txt` file
(one term per line, blank lines and '#' comments ignored) or a `.json` file
(a JSON array of strings, or `{"terms": [...]}`), repeatable for several --
see aksor_khmer_ocr_segmenter.protected_terms.loader.
`--protected-terms-dir` / `--exclude-terms-dir` are the directory form:
every `*.txt` file directly inside the given directory is merged in,
repeatable for several directories. The AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE/
_DIR and AKSOR_KHMER_OCR_EXCLUDED_TERMS_FILE/_DIR environment variables
(os.pathsep-separated paths) apply automatically without any flag.
Exclusion always wins over injection for the same term.
"""
from __future__ import annotations

import argparse
import sys

from .pipeline import process_image, process_text
from .segmenter import ZWSP


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="Raw Khmer text to segment")
    source.add_argument("--image", help="Path to an image to OCR then segment")
    parser.add_argument(
        "--lang", default="khm", help="Tesseract language code (default: khm)"
    )
    parser.add_argument(
        "--psm", type=int, default=6, help="Tesseract page segmentation mode"
    )
    parser.add_argument(
        "--visible-space",
        action="store_true",
        help="Insert a normal visible space instead of an invisible ZWSP",
    )
    parser.add_argument(
        "--protected-terms-file",
        action="append",
        default=None,
        metavar="PATH",
        help=(
            "Extra protected terms to merge in for this run: a .txt file "
            "(one term per line, '#' comments allowed) or a .json file "
            "(array of strings, or {\"terms\": [...]}). Repeatable."
        ),
    )
    parser.add_argument(
        "--exclude-terms-file",
        action="append",
        default=None,
        metavar="PATH",
        help=(
            "Terms to drop from the merge set for this run (built-in, "
            "env-supplied, or from --protected-terms-file), reverting to "
            "ICU's original behavior for just those terms. Same .txt/.json "
            "formats as --protected-terms-file. Repeatable."
        ),
    )
    parser.add_argument(
        "--protected-terms-dir",
        action="append",
        default=None,
        metavar="DIR",
        help=(
            "Directory form of --protected-terms-file: every *.txt file "
            "directly inside DIR is merged in for this run. Repeatable."
        ),
    )
    parser.add_argument(
        "--exclude-terms-dir",
        action="append",
        default=None,
        metavar="DIR",
        help=(
            "Directory form of --exclude-terms-file: every *.txt file "
            "directly inside DIR names terms to drop for this run. Repeatable."
        ),
    )
    args = parser.parse_args()

    separator = " " if args.visible_space else ZWSP

    if args.text is not None:
        result = process_text(
            args.text,
            separator=separator,
            extra_terms_file=args.protected_terms_file,
            exclude_terms_file=args.exclude_terms_file,
            extra_terms_dir=args.protected_terms_dir,
            exclude_terms_dir=args.exclude_terms_dir,
        )
    else:
        result = process_image(
            args.image,
            lang=args.lang,
            psm=args.psm,
            separator=separator,
            extra_terms_file=args.protected_terms_file,
            exclude_terms_file=args.exclude_terms_file,
            extra_terms_dir=args.protected_terms_dir,
            exclude_terms_dir=args.exclude_terms_dir,
        )

    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
