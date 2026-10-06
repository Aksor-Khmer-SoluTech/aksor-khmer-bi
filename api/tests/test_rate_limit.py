import pytest

from app import clients
from app.rate_limit import RateLimiter


class TestRateLimiter:
    def test_the_window_slides(self):
        limiter = RateLimiter(limit=lambda: 2)
        assert limiter.retry_after("a", now=0) is None
        assert limiter.retry_after("a", now=10) is None
        assert limiter.retry_after("a", now=20) == 40  # the first hit leaves the window at t=60
        assert limiter.retry_after("a", now=60) is None  # ...and then there is room again

    def test_keys_are_counted_separately(self):
        limiter = RateLimiter(limit=lambda: 1)
        assert limiter.retry_after("a", now=0) is None
        assert limiter.retry_after("b", now=0) is None
        assert limiter.retry_after("a", now=1) is not None

    def test_the_limit_is_read_on_every_request(self):
        limit = [1]
        limiter = RateLimiter(limit=lambda: limit[0])
        assert limiter.retry_after("a", now=0) is None
        assert limiter.retry_after("a", now=1) is not None
        limit[0] = 5
        assert limiter.retry_after("a", now=2) is None

    def test_reset_forgets_everything(self):
        limiter = RateLimiter(limit=lambda: 1)
        limiter.retry_after("a", now=0)
        limiter.reset()
        assert limiter.retry_after("a", now=1) is None


@pytest.mark.parametrize("value", ["", "0", "-5", "many"])
def test_a_nonsense_client_limit_falls_back_to_the_default(monkeypatch, value):
    monkeypatch.setenv(clients.ENV_LIMIT, value)
    assert clients._client_limit() == clients.DEFAULT_LIMIT_PER_MINUTE


def test_a_valid_client_limit_is_used(monkeypatch):
    monkeypatch.setenv(clients.ENV_LIMIT, "7")
    assert clients._client_limit() == 7
