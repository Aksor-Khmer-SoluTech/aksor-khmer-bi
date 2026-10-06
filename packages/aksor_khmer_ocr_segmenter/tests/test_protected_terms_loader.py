import importlib
import json

import pytest

from aksor_khmer_ocr_segmenter import segmenter
from aksor_khmer_ocr_segmenter.protected_terms.loader import (
    ENV_VAR,
    EXCLUDE_DIR_ENV_VAR,
    EXCLUDE_ENV_VAR,
    INJECT_DIR_ENV_VAR,
    INJECT_ENV_VAR,
    load_exclusions_from_dirs,
    load_exclusions_from_dirs_env,
    load_exclusions_from_env,
    load_exclusions_from_paths,
    load_terms_from_dir,
    load_terms_from_dirs,
    load_terms_from_dirs_env,
    load_terms_file,
    load_terms_from_env,
    load_terms_from_paths,
)


def _write_terms_file(path, lines):
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def test_load_terms_file_skips_blank_lines_and_comments(tmp_path):
    path = _write_terms_file(
        tmp_path / "terms.txt",
        ["# a comment", "", "ក្រុមហ៊ុនតេស្ត", "  ", "# another", "ឈ្មោះទីពីរ"],
    )
    assert load_terms_file(path) == ("ក្រុមហ៊ុនតេស្ត", "ឈ្មោះទីពីរ")


def test_load_terms_file_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_terms_file(tmp_path / "does_not_exist.txt")


def test_load_terms_from_paths_combines_multiple_files(tmp_path):
    p1 = _write_terms_file(tmp_path / "a.txt", ["ពាក្យទីមួយ"])
    p2 = _write_terms_file(tmp_path / "b.txt", ["ពាក្យទីពីរ"])
    assert load_terms_from_paths([p1, p2]) == ("ពាក្យទីមួយ", "ពាក្យទីពីរ")


def test_load_terms_from_paths_none_returns_empty():
    assert load_terms_from_paths(None) == ()


def test_load_terms_from_env_unset_returns_empty(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert load_terms_from_env() == ()


def test_load_terms_from_env_reads_file(monkeypatch, tmp_path):
    path = _write_terms_file(tmp_path / "env_terms.txt", ["ពាក្យបរិស្ថាន"])
    monkeypatch.setenv(ENV_VAR, path)
    assert load_terms_from_env() == ("ពាក្យបរិស្ថាន",)


def test_segment_merges_extra_terms_file(tmp_path):
    # A term ICU splits, but that isn't in any built-in protected_terms
    # module -- proves segment() actually consults the injected file, not
    # just coincidentally passing via a pre-existing built-in entry.
    made_up_word = "សាកល្បងមួយ"
    from aksor_khmer_ocr_segmenter.segmenter import segment

    assert made_up_word not in segmenter._DEFAULT_TERMS
    path = _write_terms_file(tmp_path / "extra.txt", [made_up_word])
    assert segment(made_up_word, extra_terms_file=path) == [made_up_word]


def test_segment_extra_terms_file_does_not_affect_other_calls(tmp_path):
    made_up_word = "សាកល្បងពីរ"
    path = _write_terms_file(tmp_path / "extra2.txt", [made_up_word])
    from aksor_khmer_ocr_segmenter.segmenter import segment

    with_file = segment(made_up_word, extra_terms_file=path)
    without_file = segment(made_up_word)
    assert with_file == [made_up_word]
    assert without_file != with_file


def test_segmenter_picks_up_env_var_at_import_time(monkeypatch, tmp_path):
    made_up_word = "សាកល្បងបី"
    path = _write_terms_file(tmp_path / "env_default.txt", [made_up_word])
    monkeypatch.setenv(ENV_VAR, path)
    try:
        reloaded = importlib.reload(segmenter)
        assert reloaded.segment(made_up_word) == [made_up_word]
    finally:
        monkeypatch.delenv(ENV_VAR, raising=False)
        importlib.reload(segmenter)  # restore module state for other tests


# --- JSON format -----------------------------------------------------------


def test_load_terms_file_json_array(tmp_path):
    path = tmp_path / "terms.json"
    path.write_text(json.dumps(["ពាក្យទីមួយ", "ពាក្យទីពីរ"]), encoding="utf-8")
    assert load_terms_file(path) == ("ពាក្យទីមួយ", "ពាក្យទីពីរ")


def test_load_terms_file_json_object_with_terms_key(tmp_path):
    path = tmp_path / "terms.json"
    path.write_text(json.dumps({"terms": ["ពាក្យទីមួយ"]}), encoding="utf-8")
    assert load_terms_file(path) == ("ពាក្យទីមួយ",)


def test_load_terms_file_json_malformed_shape_raises(tmp_path):
    path = tmp_path / "terms.json"
    path.write_text(json.dumps({"not_terms": ["x"]}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_terms_file(path)


def test_load_terms_file_json_skips_blank_entries(tmp_path):
    path = tmp_path / "terms.json"
    path.write_text(json.dumps(["ពាក្យទីមួយ", "  ", ""]), encoding="utf-8")
    assert load_terms_file(path) == ("ពាក្យទីមួយ",)


# --- Exclusion ---------------------------------------------------------


def test_load_exclusions_from_env_unset_returns_empty(monkeypatch):
    monkeypatch.delenv(EXCLUDE_ENV_VAR, raising=False)
    assert load_exclusions_from_env() == ()


def test_load_exclusions_from_paths_combines_multiple_files(tmp_path):
    p1 = _write_terms_file(tmp_path / "ex1.txt", ["ពាក្យទីមួយ"])
    p2 = _write_terms_file(tmp_path / "ex2.txt", ["ពាក្យទីពីរ"])
    assert load_exclusions_from_paths([p1, p2]) == ("ពាក្យទីមួយ", "ពាក្យទីពីរ")


def test_segment_exclude_terms_file_reverts_a_builtin_term(tmp_path):
    # A real built-in protected term (countries_places.py) -- confirm it's
    # merged by default, then confirm excluding it reverts to ICU's raw
    # (split) behavior for just this call.
    builtin_term = "ឥណ្ឌូនេស៊ី"  # Indonesia
    from aksor_khmer_ocr_segmenter.segmenter import segment

    assert segment(builtin_term) == [builtin_term]

    exclude_path = _write_terms_file(tmp_path / "exclude.txt", [builtin_term])
    excluded_result = segment(builtin_term, exclude_terms_file=exclude_path)
    assert excluded_result != [builtin_term]
    assert "".join(excluded_result) == builtin_term  # still lossless


def test_segment_exclude_terms_file_does_not_affect_other_calls(tmp_path):
    builtin_term = "ឥណ្ឌូនេស៊ី"
    exclude_path = _write_terms_file(tmp_path / "exclude2.txt", [builtin_term])
    from aksor_khmer_ocr_segmenter.segmenter import segment

    excluded_result = segment(builtin_term, exclude_terms_file=exclude_path)
    default_result = segment(builtin_term)
    assert default_result == [builtin_term]
    assert excluded_result != default_result


def test_segment_exclude_wins_over_extra_terms_file_for_same_call(tmp_path):
    # Injecting and excluding the same made-up term in the same call:
    # exclusion should win.
    made_up_word = "សាកល្បងបួន"
    from aksor_khmer_ocr_segmenter.segmenter import segment

    inject_path = _write_terms_file(tmp_path / "inject.txt", [made_up_word])
    exclude_path = _write_terms_file(tmp_path / "exclude3.txt", [made_up_word])
    result = segment(
        made_up_word, extra_terms_file=inject_path, exclude_terms_file=exclude_path
    )
    assert result != [made_up_word]


def test_segment_exclude_json_format(tmp_path):
    builtin_term = "ឥណ្ឌូនេស៊ី"
    exclude_path = tmp_path / "exclude.json"
    exclude_path.write_text(json.dumps([builtin_term]), encoding="utf-8")
    from aksor_khmer_ocr_segmenter.segmenter import segment

    assert segment(builtin_term, exclude_terms_file=str(exclude_path)) != [builtin_term]


# --- extra_terms / exclude_terms (in-memory, not file-backed) -------------
# Same behavior as the _file/_dir mechanics above, exercised via the plain
# term-list kwargs a caller with terms already in memory (e.g. a database
# row) uses instead of writing a throwaway file.


def test_segment_merges_extra_terms_list():
    made_up_word = "សាកល្បងប្រាំ"
    from aksor_khmer_ocr_segmenter.segmenter import segment

    assert made_up_word not in segmenter._DEFAULT_TERMS
    assert segment(made_up_word, extra_terms=[made_up_word]) == [made_up_word]


def test_segment_extra_terms_list_does_not_affect_other_calls():
    made_up_word = "សាកល្បងប្រាំមួយ"
    from aksor_khmer_ocr_segmenter.segmenter import segment

    with_terms = segment(made_up_word, extra_terms=[made_up_word])
    without_terms = segment(made_up_word)
    assert with_terms == [made_up_word]
    assert without_terms != with_terms


def test_segment_exclude_terms_list_reverts_a_builtin_term():
    builtin_term = "ឥណ្ឌូនេស៊ី"  # Indonesia
    from aksor_khmer_ocr_segmenter.segmenter import segment

    assert segment(builtin_term) == [builtin_term]
    excluded_result = segment(builtin_term, exclude_terms=[builtin_term])
    assert excluded_result != [builtin_term]
    assert "".join(excluded_result) == builtin_term  # still lossless


def test_segment_exclude_terms_list_wins_over_extra_terms_list_for_same_call():
    made_up_word = "សាកល្បងប្រាំពីរ"
    from aksor_khmer_ocr_segmenter.segmenter import segment

    result = segment(made_up_word, extra_terms=[made_up_word], exclude_terms=[made_up_word])
    assert result != [made_up_word]


def test_segment_exclude_terms_list_wins_over_extra_terms_file_mixed_sources():
    # The two mechanisms (file-backed and in-memory) coexist in one call --
    # exclusion still wins regardless of which side used which source.
    made_up_word = "សាកល្បងប្រាំបី"
    from aksor_khmer_ocr_segmenter.segmenter import segment

    result = segment(made_up_word, extra_terms=[made_up_word], exclude_terms=[made_up_word])
    assert result != [made_up_word]


def test_segment_extra_terms_list_combines_with_extra_terms_file(tmp_path):
    file_word = "សាកល្បងប្រាំបួន"
    list_word = "សាកល្បងដប់"
    from aksor_khmer_ocr_segmenter.segmenter import segment

    path = _write_terms_file(tmp_path / "combo.txt", [file_word])
    combined_text = file_word + list_word
    result = segment(combined_text, extra_terms_file=path, extra_terms=[list_word])
    assert result == [file_word, list_word]


def test_segment_empty_extra_terms_list_is_same_as_none():
    from aksor_khmer_ocr_segmenter.segmenter import segment

    assert segment("hello", extra_terms=[]) == segment("hello", extra_terms=None)


def test_segmenter_picks_up_exclude_env_var_at_import_time(monkeypatch, tmp_path):
    builtin_term = "ឥណ្ឌូនេស៊ី"
    path = _write_terms_file(tmp_path / "env_exclude.txt", [builtin_term])
    monkeypatch.setenv(EXCLUDE_ENV_VAR, path)
    try:
        reloaded = importlib.reload(segmenter)
        assert reloaded.segment(builtin_term) != [builtin_term]
    finally:
        monkeypatch.delenv(EXCLUDE_ENV_VAR, raising=False)
        importlib.reload(segmenter)  # restore module state for other tests


def test_inject_env_var_name_is_stable():
    # ENV_VAR is kept as a backward-compatible alias for INJECT_ENV_VAR.
    assert ENV_VAR == INJECT_ENV_VAR == "AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE"


# --- Directory-glob mode ----------------------------------------------


def test_load_terms_from_dir_merges_multiple_txt_files_sorted(tmp_path):
    _write_terms_file(tmp_path / "b.txt", ["ពាក្យទីពីរ"])
    _write_terms_file(tmp_path / "a.txt", ["ពាក្យទីមួយ"])
    # a.txt sorts before b.txt regardless of write order.
    assert load_terms_from_dir(tmp_path) == ("ពាក្យទីមួយ", "ពាក្យទីពីរ")


def test_load_terms_from_dir_ignores_non_txt_files(tmp_path):
    _write_terms_file(tmp_path / "terms.txt", ["ពាក្យទីមួយ"])
    (tmp_path / "notes.json").write_text('["ពាក្យទីពីរ"]', encoding="utf-8")
    (tmp_path / "readme.md").write_text("not terms", encoding="utf-8")
    assert load_terms_from_dir(tmp_path) == ("ពាក្យទីមួយ",)


def test_load_terms_from_dir_empty_dir_returns_empty(tmp_path):
    assert load_terms_from_dir(tmp_path) == ()


def test_load_terms_from_dir_missing_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_terms_from_dir(tmp_path / "does_not_exist")


def test_load_terms_from_dir_rejects_a_file_path(tmp_path):
    path = _write_terms_file(tmp_path / "terms.txt", ["ពាក្យទីមួយ"])
    with pytest.raises(FileNotFoundError):
        load_terms_from_dir(path)


def test_load_terms_from_dirs_combines_multiple_directories(tmp_path):
    dir1 = tmp_path / "dir1"
    dir2 = tmp_path / "dir2"
    dir1.mkdir()
    dir2.mkdir()
    _write_terms_file(dir1 / "terms.txt", ["ពាក្យទីមួយ"])
    _write_terms_file(dir2 / "terms.txt", ["ពាក្យទីពីរ"])
    assert load_terms_from_dirs([dir1, dir2]) == ("ពាក្យទីមួយ", "ពាក្យទីពីរ")


def test_load_terms_from_dirs_none_returns_empty():
    assert load_terms_from_dirs(None) == ()


def test_load_terms_from_dirs_env_unset_returns_empty(monkeypatch):
    monkeypatch.delenv(INJECT_DIR_ENV_VAR, raising=False)
    assert load_terms_from_dirs_env() == ()


def test_load_terms_from_dirs_env_reads_directory(monkeypatch, tmp_path):
    _write_terms_file(tmp_path / "terms.txt", ["ពាក្យបរិស្ថាន"])
    monkeypatch.setenv(INJECT_DIR_ENV_VAR, str(tmp_path))
    assert load_terms_from_dirs_env() == ("ពាក្យបរិស្ថាន",)


def test_load_exclusions_from_dirs_combines_multiple_directories(tmp_path):
    dir1 = tmp_path / "dir1"
    dir2 = tmp_path / "dir2"
    dir1.mkdir()
    dir2.mkdir()
    _write_terms_file(dir1 / "ex.txt", ["ពាក្យទីមួយ"])
    _write_terms_file(dir2 / "ex.txt", ["ពាក្យទីពីរ"])
    assert load_exclusions_from_dirs([dir1, dir2]) == ("ពាក្យទីមួយ", "ពាក្យទីពីរ")


def test_load_exclusions_from_dirs_env_unset_returns_empty(monkeypatch):
    monkeypatch.delenv(EXCLUDE_DIR_ENV_VAR, raising=False)
    assert load_exclusions_from_dirs_env() == ()


def test_segment_merges_extra_terms_dir(tmp_path):
    made_up_word = "សាកល្បងប្រាំ"
    from aksor_khmer_ocr_segmenter.segmenter import segment

    assert made_up_word not in segmenter._DEFAULT_TERMS
    _write_terms_file(tmp_path / "extra.txt", [made_up_word])
    assert segment(made_up_word, extra_terms_dir=str(tmp_path)) == [made_up_word]


def test_segment_extra_terms_dir_does_not_affect_other_calls(tmp_path):
    made_up_word = "សាកល្បងប្រាំមួយ"
    _write_terms_file(tmp_path / "extra.txt", [made_up_word])
    from aksor_khmer_ocr_segmenter.segmenter import segment

    with_dir = segment(made_up_word, extra_terms_dir=str(tmp_path))
    without_dir = segment(made_up_word)
    assert with_dir == [made_up_word]
    assert without_dir != with_dir


def test_segment_exclude_terms_dir_reverts_a_builtin_term(tmp_path):
    builtin_term = "ឥណ្ឌូនេស៊ី"  # Indonesia
    from aksor_khmer_ocr_segmenter.segmenter import segment

    assert segment(builtin_term) == [builtin_term]
    _write_terms_file(tmp_path / "exclude.txt", [builtin_term])
    excluded_result = segment(builtin_term, exclude_terms_dir=str(tmp_path))
    assert excluded_result != [builtin_term]
    assert "".join(excluded_result) == builtin_term  # still lossless


def test_segment_exclude_terms_dir_wins_over_extra_terms_dir(tmp_path):
    made_up_word = "សាកល្បងប្រាំពីរ"
    inject_dir = tmp_path / "inject"
    exclude_dir = tmp_path / "exclude"
    inject_dir.mkdir()
    exclude_dir.mkdir()
    _write_terms_file(inject_dir / "terms.txt", [made_up_word])
    _write_terms_file(exclude_dir / "terms.txt", [made_up_word])
    from aksor_khmer_ocr_segmenter.segmenter import segment

    result = segment(
        made_up_word, extra_terms_dir=str(inject_dir), exclude_terms_dir=str(exclude_dir)
    )
    assert result != [made_up_word]


def test_segmenter_picks_up_dir_env_var_at_import_time(monkeypatch, tmp_path):
    made_up_word = "សាកល្បងប្រាំបី"
    _write_terms_file(tmp_path / "terms.txt", [made_up_word])
    monkeypatch.setenv(INJECT_DIR_ENV_VAR, str(tmp_path))
    try:
        reloaded = importlib.reload(segmenter)
        assert reloaded.segment(made_up_word) == [made_up_word]
    finally:
        monkeypatch.delenv(INJECT_DIR_ENV_VAR, raising=False)
        importlib.reload(segmenter)  # restore module state for other tests


def test_dir_env_var_names_are_distinct_from_file_env_vars():
    assert INJECT_DIR_ENV_VAR == "AKSOR_KHMER_OCR_PROTECTED_TERMS_DIR"
    assert EXCLUDE_DIR_ENV_VAR == "AKSOR_KHMER_OCR_EXCLUDED_TERMS_DIR"
    assert INJECT_DIR_ENV_VAR != INJECT_ENV_VAR
    assert EXCLUDE_DIR_ENV_VAR != EXCLUDE_ENV_VAR
