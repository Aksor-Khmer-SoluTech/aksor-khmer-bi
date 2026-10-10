from aksor_khmer_ocr_segmenter.pipeline import process_text
from aksor_khmer_ocr_segmenter.segmenter import ZWSP


def test_process_text_inserts_break_points():
    text = "កម្ពុជាជាប្រទេសមួយស្ថិតនៅតំបន់អាស៊ីអាគ្នេយ៍"
    result = process_text(text)
    assert ZWSP in result
    assert result.replace(ZWSP, "") == text


def test_text_without_khmer_is_left_exactly_as_it_is():
    # Dates, amounts, IDs and English already break where they should; separators inside them would only break
    # what a template does with them (slicing a date, comparing a value, a number pasted out of a spreadsheet).
    for text in ["2026-09-02", "INV-2026-0131", "1,240.00", "Sokha Trading Co.", "paid in full", "", "  "]:
        assert process_text(text) == text


def test_text_with_khmer_in_it_is_still_segmented_whole():
    mixed = "ហាងលក់ទំនិញស្រីពៅ INV-2026-0131"
    result = process_text(mixed)
    assert ZWSP in result and result.replace(ZWSP, "") == mixed
