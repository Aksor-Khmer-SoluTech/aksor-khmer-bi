"""The small JSONPath a REST-backed choice list uses to find its values
(app/jsonpath.py)."""
import pytest

from app import jsonpath

RESPONSE = {
    "status": "ok",
    "data": [
        {"code": "PP01", "nameEn": "Phnom Penh", "nameKh": "ភ្នំពេញ", "meta": {"active": True, "rank": 1}, "tags": ["hq", "urban"]},
        {"code": "SR01", "nameEn": "Siem Reap", "nameKh": "សៀមរាប", "meta": {"active": False, "rank": 2}, "tags": []},
    ],
}


def find(path, data=RESPONSE):
    return jsonpath.parse(path).find(data)


@pytest.mark.parametrize(
    "path, expected",
    [
        ("$.status", ["ok"]),
        ("status", ["ok"]),  # the leading $ is optional
        ("$.data[0].code", ["PP01"]),
        ("data[1].nameEn", ["Siem Reap"]),
        ("data[-1].code", ["SR01"]),  # counted from the end
        ("$.data[*].code", ["PP01", "SR01"]),
        ("data[].code", ["PP01", "SR01"]),  # [] reads as "each item"
        ("$.data.*.code", ["PP01", "SR01"]),
        ("$['data'][0]['nameEn']", ["Phnom Penh"]),
        ('$["data"][0]["meta"]["rank"]', [1]),
        ("$.data[*].meta.active", [True, False]),
        ("$.data[0].tags[1]", ["urban"]),
        ("$.data[*].nameKh", ["ភ្នំពេញ", "សៀមរាប"]),
    ],
)
def test_paths_find_what_they_point_at(path, expected):
    assert find(path) == expected


@pytest.mark.parametrize("path", ["$.nothing", "$.data[5].code", "$.data[0].code.deeper", "$.status[0]", "$.data.code"])
def test_a_path_that_finds_nothing_finds_nothing_rather_than_failing(path):
    assert find(path) == []


def test_a_wildcard_over_an_object_reads_its_values():
    assert sorted(find("$.meta.*", {"meta": {"a": 1, "b": 2}})) == [1, 2]


def test_quoted_keys_may_hold_dots_and_escaped_quotes():
    assert find("$['a.b']", {"a.b": 1}) == [1]
    assert find(r"$['it\'s']", {"it's": 2}) == [2]
    assert find("$['a]b']", {"a]b": 3}) == [3]


@pytest.mark.parametrize(
    "path, message",
    [
        ("", "empty"),
        ("$..code", "search everywhere"),
        ("$.data[?(@.active)]", "Filters"),
        ("$.data[0:2]", "Slices"),
        ("$.data[0,1]", "Slices"),
        ("$.data[x]", "Can't read"),
        ("$.data[0", "Missing"),
        ("$data", "Unexpected"),
        ("$.", "field name"),
        ("*", "start with"),
    ],
)
def test_unsupported_or_malformed_paths_say_why(path, message):
    with pytest.raises(jsonpath.JsonPathError, match=message):
        jsonpath.parse(path)


# --- value/label expressions ------------------------------------------------


ITEM = RESPONSE["data"][0]


def evaluate(text, item=ITEM):
    return jsonpath.parse_expression(text).evaluate(item)


def test_a_plain_key_or_path_reads_one_value():
    assert evaluate("code") == "PP01"
    assert evaluate("$.nameEn") == "Phnom Penh"
    assert evaluate("meta.rank") == "1"
    assert evaluate("meta.active") == "true"


def test_a_template_mixes_text_and_paths():
    assert evaluate("${code} - ${nameEn}") == "PP01 - Phnom Penh"
    assert evaluate("${nameKh} (${meta.rank})") == "ភ្នំពេញ (1)"
    assert evaluate("${$.code}") == "PP01"
    assert evaluate("Branch ${code}") == "Branch PP01"


def test_a_missing_or_null_part_means_no_value():
    assert evaluate("nothing") is None
    assert evaluate("${code} - ${nothing}") is None
    assert evaluate("code", {"code": None}) is None


def test_a_path_to_an_object_or_list_is_an_error_not_json_in_a_dropdown():
    with pytest.raises(jsonpath.JsonPathError, match="object or a list"):
        evaluate("meta")
    with pytest.raises(jsonpath.JsonPathError, match="object or a list"):
        evaluate("${code} ${tags}")


def test_a_wildcard_is_refused_in_a_value_because_each_item_needs_one():
    with pytest.raises(jsonpath.JsonPathError, match="matches many values"):
        jsonpath.parse_expression("tags[*]", where="value")
    with pytest.raises(jsonpath.JsonPathError, match="matches many values"):
        jsonpath.parse_expression("${code} ${tags[]}", where="label")


def test_an_unclosed_placeholder_is_refused():
    with pytest.raises(jsonpath.JsonPathError, match="Unclosed"):
        jsonpath.parse_expression("${code")


# --- finding the list of items ---------------------------------------------


def test_items_default_to_the_response_itself():
    assert jsonpath.find_items(None, [1, 2]) == [1, 2]
    with pytest.raises(jsonpath.JsonPathError, match="items path"):
        jsonpath.find_items(None, {"data": []})


def test_an_items_path_may_name_the_array_or_fan_out_over_it():
    assert jsonpath.find_items(jsonpath.parse("$.data"), RESPONSE) == RESPONSE["data"]
    assert jsonpath.find_items(jsonpath.parse("$.data[*]"), RESPONSE) == RESPONSE["data"]
    groups = {"groups": [{"items": [{"c": 1}, {"c": 2}]}, {"items": [{"c": 3}]}]}
    assert jsonpath.find_items(jsonpath.parse("$.groups[*].items[*]"), groups) == [{"c": 1}, {"c": 2}, {"c": 3}]


def test_an_items_path_that_finds_nothing_is_an_empty_list():
    assert jsonpath.find_items(jsonpath.parse("$.missing"), RESPONSE) == []
