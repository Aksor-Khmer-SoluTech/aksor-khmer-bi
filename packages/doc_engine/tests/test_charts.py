import pytest

from doc_engine.charts import is_chart_spec, render_chart_png


def test_is_chart_spec_true_for_known_types():
    assert is_chart_spec({"chart": "bar", "labels": [], "series": []})
    assert is_chart_spec({"chart": "line", "labels": [], "series": []})
    assert is_chart_spec({"chart": "pie", "labels": [], "series": []})


def test_is_chart_spec_false_for_non_chart_dicts():
    assert not is_chart_spec({"label": "not a chart"})
    assert not is_chart_spec({"chart": "not-a-real-type"})
    assert not is_chart_spec("bar")
    assert not is_chart_spec(["bar"])
    assert not is_chart_spec(None)


def test_render_bar_chart_png():
    spec = {
        "chart": "bar",
        "title": "ការលក់ប្រចាំខែ",
        "labels": ["មករា", "កុម្ភៈ", "មីនា"],
        "series": [{"name": "ការលក់", "values": [100, 150, 120]}],
    }
    png = render_chart_png(spec)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 1000  # a real rendered image, not a blank stub


def test_render_line_chart_with_multiple_series():
    spec = {
        "chart": "line",
        "labels": ["Q1", "Q2", "Q3"],
        "series": [
            {"name": "2025", "values": [10, 20, 15]},
            {"name": "2026", "values": [12, 22, 18]},
        ],
    }
    png = render_chart_png(spec)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_pie_chart():
    spec = {
        "chart": "pie",
        "labels": ["A", "B", "C"],
        "series": [{"values": [30, 50, 20]}],
    }
    png = render_chart_png(spec)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_chart_respects_custom_dimensions():
    small = render_chart_png({"chart": "bar", "labels": ["A"], "series": [{"values": [1]}], "width_mm": 50, "height_mm": 30})
    large = render_chart_png({"chart": "bar", "labels": ["A"], "series": [{"values": [1]}], "width_mm": 200, "height_mm": 150})
    assert len(large) > len(small)


def test_render_chart_unknown_type_raises():
    with pytest.raises(ValueError):
        render_chart_png({"chart": "scatter", "labels": [], "series": []})
