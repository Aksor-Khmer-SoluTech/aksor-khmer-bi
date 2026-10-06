"""app/deployment_terms_sync.py -- the boot-time mirror of the
deployment-wide protected-terms floor into the database. Does not touch
rendering; see that module's docstring.
"""
from app import db
from app.deployment_terms_sync import sync_deployment_terms


def test_first_sync_creates_the_singleton_at_version_1():
    with db.SessionLocal() as session:
        result = sync_deployment_terms(session)
        session.commit()
    assert result["id"] == "default"
    assert result["version"] == 1
    assert result["terms"] == []
    assert result["exclude_terms"] == []


def test_resync_with_unchanged_files_does_not_bump_version():
    with db.SessionLocal() as session:
        first = sync_deployment_terms(session)
        session.commit()
    with db.SessionLocal() as session:
        second = sync_deployment_terms(session)
        session.commit()
    assert second["version"] == first["version"] == 1
    assert second["synced_at"] >= first["synced_at"]


def test_resync_after_a_file_changes_bumps_version(tmp_path, monkeypatch):
    terms_file = tmp_path / "terms.txt"
    terms_file.write_text("អេស៊ីលីដា\n")
    monkeypatch.setenv("AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE", str(terms_file))

    with db.SessionLocal() as session:
        first = sync_deployment_terms(session)
        session.commit()
    assert first["version"] == 1
    assert first["terms"] == ["អេស៊ីលីដា"]

    terms_file.write_text("អេស៊ីលីដា\nវឌ្ឍនៈ\n")
    with db.SessionLocal() as session:
        second = sync_deployment_terms(session)
        session.commit()
    assert second["version"] == 2
    assert set(second["terms"]) == {"អេស៊ីលីដា", "វឌ្ឍនៈ"}


def test_source_paths_reflect_configured_env_vars(tmp_path, monkeypatch):
    terms_file = tmp_path / "terms.txt"
    terms_file.write_text("term\n")
    monkeypatch.setenv("AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE", str(terms_file))
    monkeypatch.delenv("AKSOR_KHMER_OCR_EXCLUDED_TERMS_FILE", raising=False)

    with db.SessionLocal() as session:
        result = sync_deployment_terms(session)
        session.commit()
    assert result["source_paths"]["terms_file"] == str(terms_file)
    assert result["source_paths"]["exclude_file"] is None
