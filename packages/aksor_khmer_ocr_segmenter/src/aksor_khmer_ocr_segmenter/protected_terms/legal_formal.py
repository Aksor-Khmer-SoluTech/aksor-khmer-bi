"""Legal/formal Pali-Sanskrit-derived vocabulary ICU's Khmer dictionary
breaker splits incorrectly. See protected_terms/__init__.py for the rules
on adding entries.

Some entries here are borderline: the split lands on a real bound morpheme
(e.g. ភាព "-ness", ដ្ឋាន "department/office") so each half is technically an
independently valid word, unlike a mid-syllable break. Included anyway since
these compounds are common in formal/legal documents -- flagged per entry.
"""
from __future__ import annotations

TERMS: tuple[str, ...] = (
    "ព្រះរាជក្រឹត្យ",  # royal decree -- splits into ['ព្រះរាជ', 'ក្រឹត្យ']
    "លិខិតបទដ្ឋានគតិយុត្ត",  # legal instrument -- splits into ['លិខិត','បទដ្ឋាន','គតិ','យុត្ត']
    "អធិបតេយ្យភាព",  # sovereignty -- splits into ['អធិ', 'បតេយ្យ', 'ភាព']
    # Borderline (real bound suffix on each side of the split):
    "អនុលោមភាព",  # compliance -- splits into ['អនុលោម', 'ភាព']
    "អគ្គនាយកដ្ឋាន",  # general department -- splits into ['អគ្គនាយក', 'ដ្ឋាន']
    "អគ្គលេខាធិការដ្ឋាន",  # secretariat-general -- splits into ['អគ្គលេខាធិការ', 'ដ្ឋាន']
    "នីតិបញ្ញត្តិ",  # legislative -- splits into ['នីតិ', 'បញ្ញត្តិ']
)
