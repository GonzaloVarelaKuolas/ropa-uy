import httpx
import pytest

from scraper.http import FetchError, PoliteClient, RobotsDisallowed

BASE = "https://shop.example"


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_client(routes, rate=1000.0, clock=None):
    """routes: {url: list of responses (status, body)}; robots defaults to 404."""
    calls: list[httpx.Request] = []
    sleeps: list[float] = []
    queues = {url: list(responses) for url, responses in routes.items()}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        url = str(request.url)
        queue = queues.get(url)
        if queue is None:
            if url.endswith("/robots.txt"):
                return httpx.Response(404)
            raise AssertionError(f"unexpected request: {url}")
        status, body = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)

    clock = clock or FakeClock()

    def sleep(seconds):
        sleeps.append(seconds)
        clock.now += seconds

    client = PoliteClient(
        "https://example.com",
        requests_per_second=rate,
        transport=httpx.MockTransport(handler),
        clock=clock,
        sleep=sleep,
    )
    return client, calls, sleeps


def requests_to(calls, url):
    return [c for c in calls if str(c.url) == url]


def test_sends_user_agent():
    client, calls, _ = make_client({f"{BASE}/a.json": [(200, {"ok": True})]})
    assert client.get_json(f"{BASE}/a.json") == {"ok": True}
    assert requests_to(calls, f"{BASE}/a.json")[0].headers["User-Agent"] == (
        "ropa-uy-bot/0.1 (+https://example.com)"
    )


def test_retries_429_then_succeeds():
    client, calls, sleeps = make_client({f"{BASE}/a.json": [(429, {}), (200, {"n": 1})]})
    assert client.get_json(f"{BASE}/a.json") == {"n": 1}
    assert len(requests_to(calls, f"{BASE}/a.json")) == 2
    assert 2.0 in sleeps


def test_retries_5xx_and_gives_up():
    client, calls, sleeps = make_client({f"{BASE}/a.json": [(503, {})]})
    with pytest.raises(FetchError):
        client.get_json(f"{BASE}/a.json")
    assert len(requests_to(calls, f"{BASE}/a.json")) == 3
    backoffs = [s for s in sleeps if s >= 2.0]
    assert backoffs == [2.0, 4.0]


def test_retries_network_errors():
    attempts = []

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        attempts.append(request)
        if len(attempts) < 3:
            raise httpx.ConnectError("down", request=request)
        return httpx.Response(200, json={"ok": True})

    client = PoliteClient(
        "https://example.com", transport=httpx.MockTransport(handler), sleep=lambda s: None
    )
    assert client.get_json(f"{BASE}/a.json") == {"ok": True}
    assert len(attempts) == 3


def test_404_is_not_retried():
    client, calls, _ = make_client({f"{BASE}/a.json": [(404, {})]})
    with pytest.raises(FetchError, match="404"):
        client.get_json(f"{BASE}/a.json")
    assert len(requests_to(calls, f"{BASE}/a.json")) == 1


def test_invalid_json_is_fetch_error():
    client, _, _ = make_client({f"{BASE}/a.json": [(200, "<html>maintenance</html>")]})
    with pytest.raises(FetchError, match="JSON"):
        client.get_json(f"{BASE}/a.json")


def test_robots_disallow():
    robots = "User-agent: *\nDisallow: /products\n"
    client, calls, _ = make_client(
        {f"{BASE}/robots.txt": [(200, robots)], f"{BASE}/products.json": [(200, {})]}
    )
    with pytest.raises(RobotsDisallowed):
        client.get_json(f"{BASE}/products.json")
    assert requests_to(calls, f"{BASE}/products.json") == []


def test_robots_404_allows_all():
    client, _, _ = make_client({f"{BASE}/products.json": [(200, {"products": []})]})
    assert client.get_json(f"{BASE}/products.json") == {"products": []}


def test_robots_500_raises_fetch_error():
    client, calls, _ = make_client(
        {f"{BASE}/robots.txt": [(500, "")], f"{BASE}/products.json": [(200, {})]}
    )
    with pytest.raises(FetchError, match="robots"):
        client.get_json(f"{BASE}/products.json")
    assert requests_to(calls, f"{BASE}/products.json") == []


def test_robots_fetched_once_per_host():
    client, calls, _ = make_client(
        {f"{BASE}/a.json": [(200, {})], f"{BASE}/b.json": [(200, {})]}
    )
    client.get_json(f"{BASE}/a.json")
    client.get_json(f"{BASE}/b.json")
    assert len(requests_to(calls, f"{BASE}/robots.txt")) == 1


def test_rate_limit_waits_between_requests():
    clock = FakeClock()
    client, _, sleeps = make_client(
        {f"{BASE}/a.json": [(200, {})], f"{BASE}/b.json": [(200, {})]}, rate=1.0, clock=clock
    )
    client.get_json(f"{BASE}/a.json")
    sleeps.clear()
    client.get_json(f"{BASE}/b.json")
    assert sleeps == [1.0]
