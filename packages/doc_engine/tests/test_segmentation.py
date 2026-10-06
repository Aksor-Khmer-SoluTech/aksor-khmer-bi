from aksor_khmer_ocr_segmenter import process_text
from doc_engine.segmentation import segment_generic


def test_segment_generic_segments_top_level_string():
    text = "កម្ពុជាជាប្រទេសមួយស្ថិតនៅតំបន់អាស៊ីអាគ្នេយ៍"
    assert segment_generic(text) == process_text(text)


def test_segment_generic_recurses_into_lists_and_dicts():
    text = "កម្ពុជាជាប្រទេសមួយស្ថិតនៅតំបន់អាស៊ីអាគ្នេយ៍"
    data = {"a": [text, {"b": text}]}
    result = segment_generic(data)
    assert result["a"][0] == process_text(text)
    assert result["a"][1]["b"] == process_text(text)


def test_segment_generic_leaves_non_strings_untouched():
    assert segment_generic({"n": 5, "f": 1.5, "b": True, "none": None}) == {
        "n": 5,
        "f": 1.5,
        "b": True,
        "none": None,
    }


def test_segment_generic_forwards_extra_terms_to_every_string_in_the_tree():
    made_up_word = "សាកល្បងដប់មួយ"
    data = {"a": [made_up_word, {"b": made_up_word}]}
    without = segment_generic(data)
    with_terms = segment_generic(data, extra_terms=[made_up_word])
    assert with_terms["a"][0] == made_up_word
    assert with_terms["a"][1]["b"] == made_up_word
    assert without != with_terms


def test_segment_generic_forwards_exclude_terms():
    builtin_term = "ឥណ្ឌូនេស៊ី"  # Indonesia
    assert segment_generic(builtin_term) == process_text(builtin_term)
    assert segment_generic(builtin_term, exclude_terms=[builtin_term]) == process_text(
        builtin_term, exclude_terms=[builtin_term]
    )
    assert segment_generic(builtin_term, exclude_terms=[builtin_term]) != segment_generic(builtin_term)
