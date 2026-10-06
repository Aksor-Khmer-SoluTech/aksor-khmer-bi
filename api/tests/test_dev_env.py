"""app/dev_env.py: api/.env filled into the environment for local development -- gaps only,
never overriding, and never where an .env file isn't meant to apply."""
from pathlib import Path

import pytest

from app import dev_env


def test_parses_the_usual_dotenv_shapes():
    text = """
# a comment
PLAIN=value
export EXPORTED=yes
DOUBLE="has spaces and # a hash"
SINGLE='single quoted'
INLINE=before # trailing comment
EMPTY=
KEY_WITH_EQUALS=a=b=c
   SPACED   =   padded   
not a setting
9BAD=x
BAD-NAME=x
"""
    assert dev_env.parse(text) == {
        "PLAIN": "value",
        "EXPORTED": "yes",
        "DOUBLE": "has spaces and # a hash",
        "SINGLE": "single quoted",
        "INLINE": "before",
        "EMPTY": "",
        "KEY_WITH_EQUALS": "a=b=c",
        "SPACED": "padded",
    }


def test_a_hash_inside_an_unquoted_value_is_not_a_comment():
    assert dev_env.parse("TOKEN=abc#def") == {"TOKEN": "abc#def"}


def test_fills_gaps_and_never_overrides_what_is_already_set(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("A=from-file\nB=from-file\nC=\n")
    environ = {"A": "from-shell", "C": "already-set"}

    filled = dev_env.load(env_file, environ)

    assert environ == {"A": "from-shell", "B": "from-file", "C": "already-set"}
    assert filled == ["B"]


def test_an_empty_value_already_in_the_environment_counts_as_set(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("A=from-file\n")
    environ = {"A": ""}
    assert dev_env.load(env_file, environ) == []
    assert environ == {"A": ""}


def test_a_missing_or_unreadable_file_is_not_an_error(tmp_path: Path):
    assert dev_env.load(tmp_path / "nope.env", {}) == []
    assert dev_env.load(tmp_path, {}) == []  # a directory


def test_it_does_not_apply_under_pytest():
    # Which is what keeps a developer's own api/.env out of this suite.
    assert dev_env._applies() is False


@pytest.mark.parametrize("value", ["0", "false", "No", " FALSE "])
def test_it_can_be_switched_off(monkeypatch, value):
    monkeypatch.setenv(dev_env.ENV_SWITCH, value)
    assert dev_env._applies() is False


def test_it_skips_containers(monkeypatch):
    monkeypatch.delitem(__import__("sys").modules, "pytest")  # only so the other checks are reachable
    monkeypatch.setattr(dev_env.Path, "exists", lambda self: str(self) == "/.dockerenv")
    assert dev_env._applies() is False
    monkeypatch.setattr(dev_env.Path, "exists", lambda self: False)
    assert dev_env._applies() is True


def test_autoload_reports_names_and_never_values(monkeypatch, tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET_ONE=hunter2\nSECRET_TWO=hunter3\n")
    monkeypatch.setattr(dev_env, "DEFAULT_PATH", env_file)
    monkeypatch.setattr(dev_env, "_applies", lambda: True)
    monkeypatch.setattr(dev_env, "load", lambda path=env_file, environ=None: ["SECRET_ONE", "SECRET_TWO"])
    dev_env.autoload()
    assert dev_env.loaded() == ["SECRET_ONE", "SECRET_TWO"]
    assert "hunter" not in repr(dev_env.loaded())
