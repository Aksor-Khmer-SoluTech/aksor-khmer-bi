"""app/service_urls.py: database and Redis addresses built from their parts, so a password may hold any character."""
from urllib.parse import unquote, urlsplit

import pytest
from sqlalchemy.engine import make_url

from app.service_urls import REDIS_DEFAULT, SQLITE_DEFAULT, database_url, redis_url

AWKWARD = ["Pwd@123!@#$", "a/b?c#d%e:f", "with space", "ពាក្យសម្ងាត់", "quote'and\"double", "plain-hex-0123abcd"]


@pytest.mark.parametrize("password", AWKWARD)
def test_database_password_survives_any_character(password):
    url = make_url(database_url({"POSTGRES_HOST": "postgres", "POSTGRES_PASSWORD": password}))
    assert url.password == password
    assert (url.drivername, url.username, url.host, url.port, url.database) == (
        "postgresql+psycopg", "aksor", "postgres", 5432, "aksor_khmer_bi",
    )


def test_database_parts_can_be_overridden():
    url = make_url(database_url({
        "POSTGRES_HOST": "db.internal", "POSTGRES_PORT": "6543", "POSTGRES_USER": "reports",
        "POSTGRES_PASSWORD": "x", "POSTGRES_DB": "aksor",
    }))
    assert (url.username, url.host, url.port, url.database) == ("reports", "db.internal", 6543, "aksor")


def test_database_url_wins_when_set():
    explicit = "postgresql+psycopg://u:p@managed.example.com:5432/db"
    assert database_url({"DATABASE_URL": explicit, "POSTGRES_HOST": "postgres", "POSTGRES_PASSWORD": "other"}) == explicit


def test_empty_database_url_is_unset():
    # docker-compose.yml passes DATABASE_URL="" when .env doesn't set it.
    assert make_url(database_url({"DATABASE_URL": "", "POSTGRES_HOST": "postgres"})).host == "postgres"


def test_no_host_means_local_sqlite():
    assert database_url({}) == SQLITE_DEFAULT


@pytest.mark.parametrize("password", AWKWARD)
def test_redis_password_survives_any_character(password):
    parts = urlsplit(redis_url({"REDIS_HOST": "redis", "REDIS_PASSWORD": password}))
    # Celery (kombu) and redis-py both unquote the password the same way.
    assert unquote(parts.password) == password
    assert (parts.hostname, parts.port, parts.path) == ("redis", 6379, "/0")


def test_redis_without_password_and_defaults():
    assert redis_url({"REDIS_HOST": "redis"}) == "redis://redis:6379/0"
    assert redis_url({"REDIS_URL": "", "REDIS_HOST": "redis", "REDIS_PASSWORD": ""}) == "redis://redis:6379/0"
    assert redis_url({}) == REDIS_DEFAULT
    assert redis_url({"REDIS_URL": "redis://elsewhere:6379/2", "REDIS_HOST": "redis"}) == "redis://elsewhere:6379/2"
