"""Transliterated Chinese/Vietnamese surnames ICU's Khmer dictionary breaker
splits incorrectly. See protected_terms/__init__.py for the rules on adding
entries.
"""
from __future__ import annotations

TERMS: tuple[str, ...] = (
    "ង៉ែម",  # Nguyen (variant spelling) -- splits into ['ង៉ែ', 'ម']
    "វ៉ាំង",  # Wang -- splits into ['វ៉ាំ', 'ង']
    "ប៊ុយ",  # Bui -- splits into ['ប៊ុ', 'យ']
)
