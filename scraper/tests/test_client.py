"""Politeness behaviour of the HTTP client, using a fake transport (no network)."""
import httpx
import pytest

from hfr_scraper.client import (
    BlockedError,
    PoliteClient,
    RobotsGate,
    make_captcha_token,
    parse_retry_after,
)
from hfr_scraper.report import RunStats


def client_with(responses, sleeps):
    calls = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        return next(calls)

    return PoliteClient(
        "https://api.example.invalid/v4/hfr", "TestBot/1.0", delay_s=1.0, max_retries=3,
        stats=RunStats(), sleep=sleeps.append, transport=httpx.MockTransport(handler),
    )


def test_sends_a_clear_user_agent():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, json={})

    c = PoliteClient("https://x.invalid", "MyBot/2.0 (contact)", sleep=lambda s: None,
                     transport=httpx.MockTransport(handler))
    c.get_json("https://x.invalid/a")
    assert seen["ua"] == "MyBot/2.0 (contact)"


def test_retries_429_and_honours_retry_after():
    sleeps = []
    c = client_with([httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json={"ok": 1})], sleeps)
    assert c.get_json("https://api.example.invalid/x") == {"ok": 1}
    assert 7.0 in sleeps
    assert c.stats.retries == 1


def test_backs_off_exponentially_on_5xx_then_gives_up():
    sleeps = []
    c = client_with([httpx.Response(503)] * 4, sleeps)
    with pytest.raises(BlockedError):
        c.get_json("https://api.example.invalid/x")
    backoffs = [s for s in sleeps if s != 1.0]  # drop the politeness delay
    assert backoffs == [2.0, 4.0, 8.0]


def test_403_stops_immediately_and_does_not_retry():
    sleeps = []
    c = client_with([httpx.Response(403)], sleeps)
    with pytest.raises(BlockedError):
        c.get_json("https://api.example.invalid/x")
    assert c.stats.retries == 0


def test_every_request_waits_the_configured_delay():
    sleeps = []
    c = client_with([httpx.Response(200, json={})], sleeps)
    c.get_json("https://api.example.invalid/x")
    assert sleeps[0] == 1.0


def test_robots_rules_are_respected():
    gate = RobotsGate("User-agent: *\nDisallow: /private\nCrawl-delay: 5", "TestBot")
    assert gate.allowed("https://x.invalid/public")
    assert not gate.allowed("https://x.invalid/private/data")
    assert gate.crawl_delay() == 5.0


def test_missing_robots_means_allowed_but_server_error_means_stop():
    c = client_with([httpx.Response(404)], [])
    c.load_robots("https://x.invalid/robots.txt")
    assert c.robots.allowed("https://x.invalid/anything")
    c2 = client_with([httpx.Response(503)], [])
    with pytest.raises(BlockedError):
        c2.load_robots("https://x.invalid/robots.txt")


def test_retry_after_parsing_and_captcha_token_shape():
    assert parse_retry_after("12") == 12.0
    assert parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT") is None
    assert make_captcha_token("abc", "1234")  # non-empty; format is documented as unverified
