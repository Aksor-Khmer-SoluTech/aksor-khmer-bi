import pytest

from app import report_store


def test_create_report_sets_version_and_timestamps():
    meta = report_store.create_report(name="A", content=b"x", template_ext="docx")
    assert meta["version"] == 1
    assert meta["created_at"] == meta["updated_at"]


def test_update_report_meta_partial_update():
    created = report_store.create_report(name="Old", content=b"x", template_ext="docx", description="d1")
    updated = report_store.update_report_meta(created["report_id"], name="New")
    assert updated["name"] == "New"
    assert updated["description"] == "d1"  # untouched field preserved
    assert updated["version"] == 1  # metadata edits don't bump version
    assert updated["updated_at"] >= created["updated_at"]


def test_update_report_meta_not_found():
    with pytest.raises(report_store.ReportNotFoundError):
        report_store.update_report_meta("does-not-exist", name="x")


def test_replace_report_file_bumps_version_and_keeps_id():
    created = report_store.create_report(name="A", content=b"old-content", template_ext="docx")
    updated = report_store.replace_report_file(created["report_id"], b"new-content", "docx")
    assert updated["report_id"] == created["report_id"]
    assert updated["version"] == 2
    path = report_store.get_template_path(created["report_id"])
    assert path.read_bytes() == b"new-content"


def test_replace_report_file_changing_extension_removes_old_file():
    created = report_store.create_report(name="A", content=b"docx-content", template_ext="docx")
    report_store.replace_report_file(created["report_id"], b"xlsx-content", "xlsx")

    updated_meta = report_store.get_report(created["report_id"])
    assert updated_meta["template_ext"] == "xlsx"
    # the old .docx file must be gone, not left behind as an orphan
    old_path = report_store._template_path(created["report_id"], "docx")
    assert not old_path.exists()
    new_path = report_store.get_template_path(created["report_id"])
    assert new_path.suffix == ".xlsx"


def test_replace_report_file_not_found():
    with pytest.raises(report_store.ReportNotFoundError):
        report_store.replace_report_file("does-not-exist", b"x", "docx")
