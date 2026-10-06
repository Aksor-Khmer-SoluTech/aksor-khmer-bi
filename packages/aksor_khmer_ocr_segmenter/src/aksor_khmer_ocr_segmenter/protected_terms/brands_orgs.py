"""Transliterated brand/product/organization names ICU's Khmer dictionary
breaker splits incorrectly. See protected_terms/__init__.py for the rules
on adding entries.
"""
from __future__ import annotations

TERMS: tuple[str, ...] = (
    "ហ្វេសប៊ុក",  # Facebook -- splits into ['ហ្វេ', 'សប៊ុ', 'ក']
    "សាំសុង",  # Samsung -- splits into ['សាំ', 'សុង']
    "តូយូតា",  # Toyota -- splits into ['តូ', 'យូ', 'តា']
    "យូនីសេហ្វ",  # UNICEF -- splits into ['យូនី', 'សេ', 'ហ្វ']
    "អាឌីដាស",  # Adidas -- splits into ['អា', 'ឌី', 'ដាស']
    "ណៃគី",  # Nike -- splits into ['ណៃ', 'គី']
    "ផាណាសូនិក",  # Panasonic -- splits into ['ផា', 'ណា', 'សូ', 'និក']
    "សូនី",  # Sony -- splits into ['សូ', 'នី']
    "អាលីបាបា",  # Alibaba -- splits into ['អា', 'លី', 'បា', 'បា']
    "នេតហ្វ្លិច",  # Netflix -- splits into ['នេត', 'ហ្វ្', 'លិច']
    "យូធូប",  # YouTube -- splits into ['យូ', 'ធូប']
    "ធ្វីតធឺ",  # Twitter -- splits into ['ធ្វី', 'ត', 'ធឺ']
    "អ៊ីនស្តាក្រម",  # Instagram -- splits into ['អ៊ី', 'ន', 'ស្តា', 'ក្រម']
    "ស្តាបាក់",  # Starbucks -- splits into ['ស្តា', 'បាក់']
    "ខេអេហ្វស៊ី",  # KFC -- splits into ['ខេ', 'អេ', 'ហ្វ', 'ស៊ី']
    "ម៉ាកដូណាល់",  # McDonald's -- splits into ['ម៉ាក', 'ដូ', 'ណាល់']
    "ភីអិលស៊ី",  # "PLC" (Public Limited Company suffix, very common in
                  # Cambodian business names) -- splits into ['ភី','អិ','ល','ស៊ី']
    "អេស៊ីលីដា",  # ACLEDA Bank -- splits into ['អេ', 'ស៊ី', 'លីដា']
    "កាណាឌីយ៉ា",  # Canadia Bank -- splits into ['កា', 'ណា', 'ឌី', 'យ៉ា']
    "រ៉ូយ៉ាល់",  # "Royal" (bank name component) -- splits into ['រ៉ូ', 'យ៉ា', 'ល់']
    "ជីបម៉ុង",  # Chip Mong (verified via ababank.com/Chip Mong Group search --
                  # official Khmer rendering) -- splits into ['ជីប', 'ម៉ុង']
    "សហពាណិជ្ជ",  # brand-distinguishing part of Union Commercial Bank's
                    # verified official Khmer name ធនាគារសហពាណិជ្ជ (kept
                    # scoped to just this part, like ខណ្ឌ + ពោធិ៍សែនជ័យ, so
                    # the generic ធនាគារ "bank" prefix still splits off
                    # normally) -- ធនាគារសហពាណិជ្ជ splits into
                    # ['ធនាគារ', 'សហ', 'ពាណិជ្ជ']
)
