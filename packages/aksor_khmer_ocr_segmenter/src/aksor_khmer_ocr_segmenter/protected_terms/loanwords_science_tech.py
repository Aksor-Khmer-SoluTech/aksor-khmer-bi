"""Transliterated science/technology loanwords ICU's Khmer dictionary
breaker splits incorrectly. See protected_terms/__init__.py for the rules
on adding entries.
"""
from __future__ import annotations

TERMS: tuple[str, ...] = (
    "តេឡេវិស្យុន",  # television -- splits into ['តេ', 'ឡេវិ', 'ស្យុន']
    "រ៉ាឌីយូ",  # radio -- splits into ['រ៉ា', 'ឌី', 'យូ']
    "អុកស៊ីសែន",  # oxygen -- splits into ['អុក', 'ស៊ី', 'សែន']
    "អង់ទីប៊ីយោទិក",  # antibiotic -- splits into ['អង់','ទី','ប៊ី','យោ','ទិ','ក']
    "អាល្កុល",  # alcohol -- splits into ['អាល្', 'កុល']
    "អាំងស៊ុយលីន",  # insulin -- splits into ['អាំង', 'ស៊ុយ', 'លីន']
    "អេឡិចត្រុង",  # electron -- splits into ['អេ', 'ឡិច', 'ត្រុ', 'ង']
    "ម៉ាញ៉េស្យូម",  # magnesium -- splits into ['ម៉ា', 'ញ៉េស្យូម']
)
