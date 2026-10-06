"""Native (non-transliterated) Khmer given names ICU's Khmer dictionary
breaker splits incorrectly. See protected_terms/__init__.py for the rules
on adding entries.

IMPORTANT SCOPE NOTE: unlike country/brand/legal vocabulary, personal names
are combinatorially unbounded -- there is no finite list that covers every
Khmer name a real user might submit (e.g. via an API's `taxpayer_name`
field). The entries below are illustrative common cases caught during
testing, not an exhaustive or authoritative name list. For a name specific
to one deployment's real data (a known VIP client, a recurring test
fixture), prefer the injectable terms-file mechanism
(protected_terms/loader.py) scoped to that deployment over adding it here.
Only add an entry here if the same mis-split is likely to recur broadly
across many different real users, not just one individual.
"""
from __future__ import annotations

TERMS: tuple[str, ...] = (
    "សុគន្ធា",  # Sokunthea -- splits into ['សុ', 'គន្ធា']
    "ដារា",  # Dara -- splits into ['ដា', 'រា']
    "ចន្ទនីរដ្ឋ",  # Chandaneth -- splits into ['ចន្ទ', 'នី', 'រដ្ឋ']
    "សុវណ្ណដារា",  # Sovandara -- splits into ['សុវណ្ណ', 'ដា', 'រា']
    "ធារ៉ា",  # Thara -- splits into ['ធា', 'រ៉ា']
    "ចាន់ណារិទ្ធ",  # Channarith -- splits into ['ចាន់', 'ណា', 'រិទ្ធ']
    "សុផាត់",  # Sopheak (variant spelling) -- splits into ['សុ', 'ផាត់']
    "ណារិន",  # Narin -- splits into ['ណា', 'រិន']
    # Borderline (both halves are real, independently standalone words --
    # "moon"/"to say" and "girl"/"she" respectively -- but each reads as
    # one given name in practice):
    "ចាន់ថា",  # Chantha -- splits into ['ចាន់', 'ថា']
    "ស្រីនាង",  # Sreynang -- splits into ['ស្រី', 'នាង']
)
