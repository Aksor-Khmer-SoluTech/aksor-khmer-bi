"""Khmer word segmentation.

Khmer is normally written with no spaces between words. Renderers that only
break lines at whitespace (e.g. WeasyPrint/Pango) will treat an entire
unspaced sentence as a single unbreakable token and let it overflow instead
of wrapping.

This module uses ICU's dictionary-based word BreakIterator (the same
mechanism LibreOffice/Word rely on for Khmer line-breaking) to find the
correct word boundaries in unspaced text, so a caller can insert real spaces
or invisible zero-width spaces (U+200B) at those boundaries before handing
the text to a layout engine.
"""
from __future__ import annotations

from typing import Sequence

import icu

from .protected_terms import PROTECTED_TERMS
from .protected_terms.loader import (
    load_exclusions_from_dirs,
    load_exclusions_from_dirs_env,
    load_exclusions_from_env,
    load_exclusions_from_paths,
    load_terms_from_dirs,
    load_terms_from_dirs_env,
    load_terms_from_env,
    load_terms_from_paths,
)

ZWSP = "​"

_KM_LOCALE = icu.Locale("km")

# Terms supplied via AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE/_DIR and
# AKSOR_KHMER_OCR_EXCLUDED_TERMS_FILE/_DIR, read once at import time --
# combined with PROTECTED_TERMS to form the default term set used when a
# call doesn't pass extra_terms_file/extra_terms_dir/exclude_terms_file/
# exclude_terms_dir.
_ENV_INJECT_TERMS = load_terms_from_env() + load_terms_from_dirs_env()
_ENV_EXCLUDE_TERMS = load_exclusions_from_env() + load_exclusions_from_dirs_env()
_BASE_TERMS = tuple(dict.fromkeys(PROTECTED_TERMS + _ENV_INJECT_TERMS))
_DEFAULT_TERMS = tuple(t for t in _BASE_TERMS if t not in set(_ENV_EXCLUDE_TERMS))

# Longest-first so a longer protected term is tried before a shorter one
# that happens to be a prefix of it.
_DEFAULT_SORTED = sorted(_DEFAULT_TERMS, key=len, reverse=True)


def _sorted_terms(
    extra_terms_file: str | list[str] | None,
    exclude_terms_file: str | list[str] | None,
    extra_terms_dir: str | list[str] | None = None,
    exclude_terms_dir: str | list[str] | None = None,
    extra_terms: Sequence[str] | None = None,
    exclude_terms: Sequence[str] | None = None,
) -> list[str]:
    """The longest-first term list to merge against for one call: the
    default set (built-ins + AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE/_DIR,
    minus AKSOR_KHMER_OCR_EXCLUDED_TERMS_FILE/_DIR) plus whatever
    `extra_terms_file`/`extra_terms_dir`/`extra_terms` add and
    `exclude_terms_file`/`exclude_terms_dir`/`exclude_terms` remove for
    just this call. Exclusion always wins over injection, regardless of
    which of these six sources either side came from.

    `extra_terms`/`exclude_terms` are plain term strings (not paths) --
    a caller that already has its terms in memory (e.g. a database row)
    passes them directly here instead of writing a throwaway file just
    to reuse the `_file`/`_dir` loaders.
    """
    if (
        extra_terms_file is None
        and exclude_terms_file is None
        and extra_terms_dir is None
        and exclude_terms_dir is None
        and not extra_terms
        and not exclude_terms
    ):
        return _DEFAULT_SORTED
    file_inject_terms = load_terms_from_paths(extra_terms_file) + load_terms_from_dirs(
        extra_terms_dir
    )
    excluded = (
        set(_ENV_EXCLUDE_TERMS)
        | set(load_exclusions_from_paths(exclude_terms_file))
        | set(load_exclusions_from_dirs(exclude_terms_dir))
        | set(exclude_terms or ())
    )
    combined = tuple(dict.fromkeys(_BASE_TERMS + file_inject_terms + tuple(extra_terms or ())))
    combined = tuple(t for t in combined if t not in excluded)
    return sorted(combined, key=len, reverse=True)


def _merge_protected_terms(words: list[str], sorted_terms: list[str]) -> list[str]:
    """Re-merge adjacent ICU tokens that together spell out a known
    protected term, undoing an incorrect ICU dictionary split for that
    specific known case.

    Greedy, left-to-right, longest-match scan: at each position, try each
    protected term (longest first) to see whether the concatenation of the
    next N tokens equals that term exactly; if so, emit it as a single
    merged token and advance past all N tokens.
    """
    merged: list[str] = []
    i = 0
    n = len(words)
    while i < n:
        matched = False
        for term in sorted_terms:
            acc = ""
            j = i
            while j < n and len(acc) < len(term):
                acc += words[j]
                j += 1
                if acc == term:
                    merged.append(term)
                    i = j
                    matched = True
                    break
            if matched:
                break
        if not matched:
            merged.append(words[i])
            i += 1
    return merged


def segment(
    text: str,
    extra_terms_file: str | list[str] | None = None,
    exclude_terms_file: str | list[str] | None = None,
    extra_terms_dir: str | list[str] | None = None,
    exclude_terms_dir: str | list[str] | None = None,
    extra_terms: Sequence[str] | None = None,
    exclude_terms: Sequence[str] | None = None,
) -> list[str]:
    """Split Khmer text into words using ICU's dictionary-based boundary
    analysis. Works on already-spaced text too (spaces are just one more
    boundary ICU recognizes), so it's safe to run on mixed content.

    `extra_terms_file` optionally names one path or a list of paths to
    protected-terms files (`.txt`, one term per line, or `.json` -- see
    protected_terms/loader.py) to merge in for this call only, on top of
    the built-ins and whatever AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE already
    supplies. `extra_terms_dir` is the directory form of the same thing --
    one path or a list of directories, every `*.txt` file inside each one
    merged in, on top of whatever AKSOR_KHMER_OCR_PROTECTED_TERMS_DIR
    already supplies. `extra_terms` is the in-memory form -- a plain list
    of term strings, for a caller that already has them (e.g. a database
    row) rather than a file on disk.

    `exclude_terms_file`/`exclude_terms_dir`/`exclude_terms` are the
    inverse: terms (built-in, env-supplied, or from any of the extra_*
    sources above) to drop from the merge set for this call, reverting
    to ICU's original (unmerged) behavior for just those terms. Same
    file/directory/in-memory mechanics, on top of whatever
    AKSOR_KHMER_OCR_EXCLUDED_TERMS_FILE/_DIR already supplies.
    """
    if not text:
        return []

    boundary_iter = icu.BreakIterator.createWordInstance(_KM_LOCALE)
    boundary_iter.setText(text)

    words: list[str] = []
    start = 0
    for end in boundary_iter:
        words.append(text[start:end])
        start = end
    return _merge_protected_terms(
        words,
        _sorted_terms(extra_terms_file, exclude_terms_file, extra_terms_dir, exclude_terms_dir, extra_terms, exclude_terms),
    )


def insert_breaks(
    text: str,
    separator: str = ZWSP,
    extra_terms_file: str | list[str] | None = None,
    exclude_terms_file: str | list[str] | None = None,
    extra_terms_dir: str | list[str] | None = None,
    exclude_terms_dir: str | list[str] | None = None,
    extra_terms: Sequence[str] | None = None,
    exclude_terms: Sequence[str] | None = None,
) -> str:
    """Return `text` with `separator` inserted at every ICU word boundary.

    Use `separator=ZWSP` (default) to give a layout engine break
    opportunities without changing how the text visually looks (no
    visible extra spaces) — this is the standard fix for Khmer/Lao/Thai
    typesetting in engines without native dictionary-based line breaking.

    Use `separator=" "` instead if you want visibly spaced-out words, e.g.
    to make OCR'd or copy-pasted unspaced text easier to read/edit.

    See `segment()` for `extra_terms_file`/`extra_terms_dir`/`extra_terms`/
    `exclude_terms_file`/`exclude_terms_dir`/`exclude_terms`.
    """
    words = segment(
        text,
        extra_terms_file=extra_terms_file,
        exclude_terms_file=exclude_terms_file,
        extra_terms_dir=extra_terms_dir,
        exclude_terms_dir=exclude_terms_dir,
        extra_terms=extra_terms,
        exclude_terms=exclude_terms,
    )
    # ICU's word iterator also yields "words" that are pure whitespace
    # between real tokens; don't double up separators around those.
    pieces: list[str] = []
    for word in words:
        if word.isspace():
            pieces.append(word)
        else:
            pieces.append(word)
            pieces.append(separator)
    result = "".join(pieces)
    # Trim a trailing separator we may have added after the last word.
    if separator and result.endswith(separator):
        result = result[: -len(separator)]
    return result
