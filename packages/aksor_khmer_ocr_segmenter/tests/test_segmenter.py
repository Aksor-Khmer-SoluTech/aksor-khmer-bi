import pytest

from aksor_khmer_ocr_segmenter.protected_terms import PROTECTED_TERMS
from aksor_khmer_ocr_segmenter.segmenter import ZWSP, insert_breaks, segment

UNSPACED = (
    "កម្ពុជាជាប្រទេសមួយស្ថិតនៅតំបន់អាស៊ីអាគ្នេយ៍មានទីរាជធានីគឺភ្នំពេញ"
)


def test_segment_splits_unspaced_text_into_multiple_words():
    words = segment(UNSPACED)
    assert len(words) > 5
    assert "".join(words) == UNSPACED  # segmentation must be lossless


def test_insert_breaks_default_zwsp_is_invisible():
    result = insert_breaks(UNSPACED)
    assert ZWSP in result
    # Stripping the ZWSP must reproduce the original text exactly.
    assert result.replace(ZWSP, "") == UNSPACED


def test_insert_breaks_visible_space():
    result = insert_breaks(UNSPACED, separator=" ")
    assert " " in result
    assert result.replace(" ", "") == UNSPACED


def test_segment_is_safe_on_already_spaced_text():
    spaced = "មនុស្សទាំងអស់ កើតមកមានសេរីភាព"
    words = segment(spaced)
    assert "".join(words) == spaced


def test_segment_empty_string():
    assert segment("") == []


@pytest.mark.parametrize("term", PROTECTED_TERMS)
def test_segment_merges_known_protected_transliterations(term):
    # Every entry in protected_terms.PROTECTED_TERMS is a term ICU's Khmer
    # dictionary breaker is known to split incorrectly (usually
    # mid-syllable); segment() must re-merge it into a single token.
    assert segment(term) == [term]


def test_segment_does_not_regress_already_correct_transliterations():
    # These are NOT in the protected list because ICU already gets them
    # right in the currently pinned environment; if a future ICU/CLDR
    # upgrade breaks one of these, add it to protected_terms.PROTECTED_TERMS
    # and pin it alongside the cases above.
    assert segment("ឥវ៉ាន់") == ["ឥវ៉ាន់"]
    assert segment("អ៊ីស្រាអែល") == ["អ៊ីស្រាអែល"]
    assert segment("អូស្ត្រាលី") == ["អូស្ត្រាលី"]
    assert segment("បារាំង") == ["បារាំង"]


def test_insert_breaks_does_not_split_protected_terms_mid_word():
    text = "ខ្ញុំមកពីប្រទេសឥណ្ឌូនេស៊ី"
    result = insert_breaks(text)
    assert result.replace(ZWSP, "") == text  # lossless
    term = "ឥណ្ឌូនេស៊ី"
    start = result.index(term[0])
    assert ZWSP not in result[start : start + len(term)]
