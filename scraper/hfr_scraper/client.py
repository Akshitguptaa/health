"""Polite HTTP client for the NHPR public facility search.

EXPERIMENTAL / UNVERIFIED against the live site. The search endpoint is gated
by a numeric image captcha that a human has to read, so this code could not be
exercised end to end. Everything the site operator would care about (robots.txt,
User-Agent, request rate, backoff, no attempt to defeat the captcha) is
implemented and unit-tested; the exact query-parameter names and captcha-token
format below are best guesses from the public web app and may need adjusting
against your browser's network tab.
"""
from __future__ import annotations

import base64
import time
from typing import Any
from urllib import robotparser

import httpx

from .report import RunStats


class BlockedError(RuntimeError):
    """The site refused us (401/403/captcha rejected). We stop, we never work around it."""


class RobotsGate:
    def __init__(self, robots_txt: str, user_agent: str) -> None:
        self.parser = robotparser.RobotFileParser()
        self.parser.parse(robots_txt.splitlines())
        self.user_agent = user_agent

    def allowed(self, url: str) -> bool:
        return self.parser.can_fetch(self.user_agent, url)

    def crawl_delay(self) -> float:
        return float(self.parser.crawl_delay(self.user_agent) or 0)


def parse_retry_after(value: str | None) -> float | None:
    if value and value.strip().isdigit():
        return float(value.strip())
    return None


def make_captcha_token(captcha_id: str, answer: str) -> str:
    """UNVERIFIED guess: the web app sends `Authorization: Captcha_<token>`.
    Compare with a real search request in your browser's network tab."""
    return base64.b64encode(f"{captcha_id}:{answer}".encode()).decode()


def build_search_params(state: str, district: str, page: int, page_size: int = 10) -> dict[str, Any]:
    """UNVERIFIED guess at the query parameters (see module docstring)."""
    return {"state": state, "dist": district, "pageNo": page, "pageSize": page_size}


class PoliteClient:
    def __init__(
        self,
        base_url: str,
        user_agent: str,
        api_key: str = "",
        delay_s: float = 2.0,
        max_retries: int = 5,
        stats: RunStats | None = None,
        sleep=time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"User-Agent": user_agent, "Accept": "application/json"}
        if api_key:
            headers["apikey"] = api_key
        self.http = httpx.Client(headers=headers, timeout=30, transport=transport)
        self.base_url = base_url.rstrip("/")
        self.delay_s = delay_s
        self.max_retries = max_retries
        self.stats = stats or RunStats()
        self._sleep = sleep
        self.robots: RobotsGate | None = None
        self.user_agent = user_agent

    def load_robots(self, robots_url: str) -> None:
        """Fetch robots.txt once. A missing file (404) means no restrictions;
        any other failure stops the crawl rather than guessing."""
        r = self.http.get(robots_url)
        if r.status_code == 404:
            self.robots = RobotsGate("User-agent: *\nAllow: /", self.user_agent)
        elif r.status_code == 200:
            self.robots = RobotsGate(r.text, self.user_agent)
            self.delay_s = max(self.delay_s, self.robots.crawl_delay())
        else:
            raise BlockedError(f"robots.txt returned HTTP {r.status_code}; not crawling.")

    def get_json(self, url: str, **kwargs: Any) -> Any:
        if self.robots and not self.robots.allowed(url):
            raise BlockedError(f"robots.txt disallows {url}")
        for attempt in range(self.max_retries + 1):
            self._sleep(self.delay_s)
            try:
                r = self.http.get(url, **kwargs)
            except httpx.TransportError:
                r = None
            if r is not None and r.status_code in (401, 403):
                raise BlockedError(
                    f"HTTP {r.status_code} from {url}. Blocked or captcha rejected: stopping."
                )
            if r is not None and r.status_code < 400:
                self.stats.pages_fetched += 1
                return r.json()
            if r is not None and r.status_code not in (429, 500, 502, 503, 504):
                r.raise_for_status()
            if attempt == self.max_retries:
                raise BlockedError(f"Gave up on {url} after {self.max_retries} retries.")
            self.stats.retries += 1
            wait = parse_retry_after(r.headers.get("Retry-After")) if r is not None else None
            self._sleep(wait if wait is not None else min(60.0, 2.0 ** (attempt + 1)))
        raise AssertionError("unreachable")
