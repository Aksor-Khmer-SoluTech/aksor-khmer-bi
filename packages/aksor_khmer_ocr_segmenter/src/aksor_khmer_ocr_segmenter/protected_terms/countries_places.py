"""Transliterated country/city names ICU's Khmer dictionary breaker splits
incorrectly. See protected_terms/__init__.py for the rules on adding entries.
"""
from __future__ import annotations

TERMS: tuple[str, ...] = (
    "ឥណ្ឌូនេស៊ី",  # Indonesia -- splits into ['ឥណ្ឌូ', 'នេ', 'ស៊ី']
    "ប៊ុនថន",  # Bhutan -- splits into ['ប៊ុ', 'ន', 'ថន']
    "ហូឡង់",  # Netherlands -- splits into ['ហូ', 'ឡង់']
    "អារ៉ាប៊ីសាអូឌីត",  # Saudi Arabia -- splits into ['អា', 'រ៉ា', 'ប៊ី', 'សា', 'អូឌីត']
    "កាតា",  # Qatar -- splits into ['កា', 'តា']
    "ស៊ីង្ហបុរី",  # Singapore -- splits into ['ស៊ីង្', 'ហបុ', 'រី']
    "ម៉ីយ៉ាន់ម៉ា",  # Myanmar (alt spelling) -- splits into ['ម៉ី', 'យ៉ាន់', 'ម៉ា']
    "ណេប៉ាល់",  # Nepal -- splits into ['ណេ', 'ប៉ាល់']
    "បង់ក្លាដែស",  # Bangladesh -- splits into ['បង់', 'ក្លា', 'ដែស']
    "អាហ្គានីស្ថាន",  # Afghanistan -- splits into ['អាហ្', 'គា', 'នី', 'ស្ថាន']
    "ដិន្នឺម៉ាក",  # Denmark -- splits into ['ដិ', 'ន្នឺ', 'ម៉ាក']
    "ប៊ែងកុក",  # Bangkok -- splits into ['ប៊ែង', 'កុក']
    "ញូវយ៉ក",  # New York -- splits into ['ញូ', 'វយ៉', 'ក']
    "ប៊្រុចសែល",  # Brussels -- splits into ['ប៊្រុច', 'សែល']
    "ស្លូវ៉េនី",  # Slovenia -- splits into ['ស្លូ', 'វ៉េ', 'នី']
    "ក្រូអាស៊ី",  # Croatia -- splits into ['ក្រូ', 'អាស៊ី']
    "សឺប៊ី",  # Serbia -- splits into ['សឺ', 'ប៊ី']
    "ប៊ូស្នី",  # Bosnia -- splits into ['ប៊ូ', 'ស្នី']
    "អ៊ូសបេគីស្ថាន",  # Uzbekistan -- splits into ['អ៊ូ', 'សបេ', 'គី', 'ស្ថាន']
    "តាជីគីស្ថាន",  # Tajikistan -- splits into ['តាជី', 'គី', 'ស្ថាន']
    "គូវ៉ែត",  # Kuwait -- splits into ['គូ', 'វ៉ែត']
    "យេម៉ែន",  # Yemen -- splits into ['យេ', 'ម៉ែ', 'ន']
    "ទុយនីស៊ី",  # Tunisia -- splits into ['ទុយ', 'នី', 'ស៊ី']
    "ណីហ្សេរីយ៉ា",  # Nigeria -- splits into ['ណី', 'ហ្សេ', 'រី', 'យ៉ា']
    "ហ្កាណា",  # Ghana -- splits into ['ហ្កា', 'ណា']
    "ចាមេកា",  # Jamaica -- splits into ['ចា', 'មេ', 'កា']
    "វេនេស៊ុយអេឡា",  # Venezuela -- splits into ['វេនេ', 'ស៊ុយ', 'អេ', 'ឡា']
)
