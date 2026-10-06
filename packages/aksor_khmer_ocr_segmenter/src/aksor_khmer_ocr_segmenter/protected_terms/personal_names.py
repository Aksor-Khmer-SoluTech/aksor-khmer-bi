"""Transliterated personal names ICU's Khmer dictionary breaker splits
incorrectly. See protected_terms/__init__.py for the rules on adding entries.
"""
from __future__ import annotations

TERMS: tuple[str, ...] = (
    "ម៉ាយខល",  # Michael -- splits into ['ម៉ាយ', 'ខល']
    "រ៉ូប៊ឺត",  # Robert -- splits into ['រ៉ូប៊ឺ', 'ត']
    "វ៉ិលសុន",  # Wilson -- splits into ['វ៉ិល', 'សុន']
    "ម៉ារី",  # Mary -- splits into ['ម៉ា', 'រី']
    "អេលីសាបិត",  # Elizabeth -- splits into ['អេ', 'លី', 'សា', 'បិត']
    "ដេវីឌ",  # David -- splits into ['ដេ', 'វី', 'ឌ']
    "ចេនណាហ្វើ",  # Jennifer -- splits into ['ចេ', 'នណា', 'ហ្វើ']
    "ស្មីធ",  # Smith -- splits into ['ស្មី', 'ធ']
    "អាឡិចសាន់ឌឺ",  # Alexander -- splits into ['អា', 'ឡិច', 'សាន់', 'ឌឺ']
    "វ៉ាឡិនធីណា",  # Valentina -- splits into ['វ៉ា', 'ឡិន', 'ធី', 'ណា']
    "គ្រីស្ទីណា",  # Christina -- splits into ['គ្រី', 'ស្ទី', 'ណា']
    "ណាតាសា",  # Natasha -- splits into ['ណា', 'តា', 'សា']
    "ចាក់សុន",  # Jackson -- splits into ['ចា', 'ក់', 'សុន']
    "ថូម៉ាស",  # Thomas -- splits into ['ថូ', 'ម៉ាស']
    "វិល្លៀម",  # William -- splits into ['វិល្', 'លៀម']
    "ចេណេត",  # Janet -- splits into ['ចេ', 'ណេត']
    "សាមានតា",  # Samantha -- splits into ['សា', 'មាន', 'តា']
    "ណាតាលី",  # Natalie -- splits into ['ណា', 'តា', 'លី']
    "អូលីវីយេ",  # Olivier -- splits into ['អូ', 'លី', 'វី', 'យេ']
    "ដានីយែល",  # Daniel -- splits into ['ដា', 'នី', 'យែល']
    "ចូសែប",  # Joseph -- splits into ['ចូ', 'សែប']
    "ភីធើ",  # Peter -- splits into ['ភី', 'ធើ']
    "ស្តេផានី",  # Stephanie -- splits into ['ស្តេ', 'ផា', 'នី']
)
