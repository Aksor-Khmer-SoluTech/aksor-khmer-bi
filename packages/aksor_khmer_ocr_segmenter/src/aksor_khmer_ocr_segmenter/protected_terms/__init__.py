"""Small, explicitly-scoped lists of transliterated loanwords/proper names
and formal-register compounds that ICU's Khmer dictionary breaker is known
to split incorrectly (usually mid-syllable) in at least one observed
ICU/CLDR version.

This is NOT a general Khmer word dictionary and is not meant to become one —
see docs/khmer-line-breaking.md for why aksor_khmer_ocr_segmenter deliberately
does not hand-maintain a full word list. Add an entry only when you have
concretely observed ICU mis-segmenting it, with a regression test in
tests/test_segmenter.py pinning the case (the test suite parametrizes over
PROTECTED_TERMS, so a new entry is covered automatically).

Entries are grouped into one module per category so each list stays easy to
scan and extend:
    countries_places.py         -- transliterated country/city names
    khmer_places.py              -- Cambodian domestic administrative names
    personal_names.py           -- transliterated personal names
    native_personal_names.py    -- native (non-transliterated) Khmer given names
    surnames.py                 -- transliterated Chinese/Vietnamese surnames
    loanwords_science_tech.py   -- science/technology loanwords
    brands_orgs.py              -- brand/product/organization names
    legal_formal.py             -- legal/formal Pali-Sanskrit vocabulary

Observed against PyICU 2.16.2 / ICU4C 78.3.
"""
from __future__ import annotations

from . import (
    brands_orgs,
    countries_places,
    khmer_places,
    legal_formal,
    loanwords_science_tech,
    native_personal_names,
    personal_names,
    surnames,
)

PROTECTED_TERMS: tuple[str, ...] = (
    countries_places.TERMS
    + khmer_places.TERMS
    + personal_names.TERMS
    + native_personal_names.TERMS
    + surnames.TERMS
    + loanwords_science_tech.TERMS
    + brands_orgs.TERMS
    + legal_formal.TERMS
)
