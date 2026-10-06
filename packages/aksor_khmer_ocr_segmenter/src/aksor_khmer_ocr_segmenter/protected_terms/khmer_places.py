"""Cambodian domestic administrative place names (district/commune level)
ICU's Khmer dictionary breaker splits incorrectly. Unlike top-level
provinces (all 21 tested clean -- see countries_places.py module docstring
history), Phnom Penh khan/sangkat names are more prone to mis-splits since
they're less standardized lexicon entries. See protected_terms/__init__.py
for the rules on adding entries.

Found via an end-to-end OCR round trip on a real Cambodian property-tax
address field, not synthetic testing.
"""
from __future__ import annotations

TERMS: tuple[str, ...] = (
    "ពោធិ៍សែនជ័យ",  # Porsenchey (Phnom Penh khan) -- splits into ['ពោធិ៍', 'សែន', 'ជ័យ']
    "ចបារអំពៅ",  # Chbar Ampov (Phnom Penh khan) -- splits into ['ចបា', 'រ', 'អំពៅ']
    "ជ្រោយចង្វារ",  # Chroy Changvar (Phnom Penh khan) -- splits into ['ជ្រោយ', 'ចង្វា', 'រ']
    "វេងស្រេង",  # Veng Sreng (major Phnom Penh boulevard) -- splits into ['វេ', 'ង', 'ស្រេង']
    # Borderline (real words on each side of the split):
    "ប្រាំពីរមករា",  # 7 Makara (Phnom Penh khan) -- "seven"+"January" -- splits into ['ប្រាំពីរ', 'មករា']
    "ពិភពថ្មី",  # "New World" (common borey/development name) -- "world"+"new" -- splits into ['ពិភព', 'ថ្មី']
)
