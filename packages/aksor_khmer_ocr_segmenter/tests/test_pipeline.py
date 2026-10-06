from aksor_khmer_ocr_segmenter.pipeline import process_text
from aksor_khmer_ocr_segmenter.segmenter import ZWSP


def test_process_text_inserts_break_points():
    text = "កម្ពុជាជាប្រទេសមួយស្ថិតនៅតំបន់អាស៊ីអាគ្នេយ៍"
    result = process_text(text)
    assert ZWSP in result
    assert result.replace(ZWSP, "") == text
