"""An HTTP client that is polite to the stores it reads.

It identifies itself, follows robots.txt, waits between requests to the same
host, and retries temporary failures with a growing pause.
"""

import json
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "ropa-uy-bot/0.1 (+{contact_url})"
RETRY_STATUSES = {429} | set(range(500, 600))


class FetchError(Exception):
    """A request failed after retries, or returned a status that isn't retried."""


class RobotsDisallowed(FetchError):
    """robots.txt does not allow this URL."""


class PoliteClient:
    def __init__(
        self,
        contact_url: str,
        requests_per_second: float = 1.0,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 3,
        backoff_base: float = 2.0,
        timeout: float = 20.0,
    ):
        self.user_agent = USER_AGENT.format(contact_url=contact_url)
        self._interval = 1.0 / requests_per_second
        self._clock = clock
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base
        self._http = httpx.Client(
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": self.user_agent},
            follow_redirects=True,
        )
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last_request: dict[str, float] = {}

    def get_json(self, url: str) -> Any:
        if not self._robots_allows(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")
        response = self._request(url)
        if response.status_code != 200:
            raise FetchError(f"GET {url} returned {response.status_code}")
        try:
            return response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise FetchError(f"GET {url} did not return JSON") from None

    def close(self) -> None:
        self._http.close()

    def _robots_allows(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            self._robots[origin] = self._load_robots(origin)
        parser = self._robots[origin]
        return parser is None or parser.can_fetch(self.user_agent, url)

    def _load_robots(self, origin: str) -> RobotFileParser | None:
        robots_url = f"{origin}/robots.txt"
        try:
            response = self._request(robots_url)
        except FetchError as exc:
            raise FetchError(f"could not read robots.txt at {robots_url}: {exc}") from None
        if response.status_code == 404:
            return None  # no robots.txt: everything is allowed
        if response.status_code != 200:
            raise FetchError(f"could not read robots.txt at {robots_url}: {response.status_code}")
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        return parser

    def _request(self, url: str) -> httpx.Response:
        """GET with retries. Returns the last response; raises FetchError if none came back."""
        for attempt in range(1, self._max_attempts + 1):
            self._wait_for_turn(url)
            try:
                response = self._http.get(url)
            except httpx.TransportError as exc:
                if attempt == self._max_attempts:
                    raise FetchError(f"GET {url} failed: {exc}") from None
            else:
                if response.status_code not in RETRY_STATUSES:
                    return response
                if attempt == self._max_attempts:
                    raise FetchError(f"GET {url} returned {response.status_code} after {attempt} attempts")
            self._sleep(self._backoff_base * 2 ** (attempt - 1))
        raise AssertionError("unreachable")

    def _wait_for_turn(self, url: str) -> None:
        host = urlsplit(url).netloc
        last = self._last_request.get(host)
        if last is not None:
            remaining = self._interval - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request[host] = self._clock()
