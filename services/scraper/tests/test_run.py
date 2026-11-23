import json
from decimal import Decimal

import pytest

from scraper import platforms
from scraper.__main__ import main
from scraper.http import FetchError
from scraper.models import Product, StoreConfig
from scraper.run import run_stores

A = StoreConfig(slug="a", name="A", url="https://a.uy", platform="fake")
B = StoreConfig(slug="b", name="B", url="https://b.uy", platform="fake")

STORES_YAML = """
stores:
  - slug: a
    name: A
    url: https://a.uy
    platform: fake
  - slug: b
    name: B
    url: https://b.uy
    platform: fake
"""


def product(store, external_id="1"):
    return Product(
        store_slug=store.slug,
        external_id=external_id,
        title="Buzo",
        url=f"{store.url}/products/buzo",
        price=Decimal("1490.00"),
        currency="UYU",
        sizes=["M"],
        in_stock=True,
        raw={"id": external_id},
    )


class RecordingSink:
    def __init__(self):
        self.events = []

    def store_started(self, store):
        self.events.append(("started", store.slug))

    def store_succeeded(self, store, products):
        self.events.append(("succeeded", store.slug, len(products)))

    def store_failed(self, store, error):
        self.events.append(("failed", store.slug, error))


def reader_from(behaviour):
    """behaviour: {slug: list of products, or an exception to raise}."""
    calls = []

    def read(store, client):
        calls.append(store.slug)
        outcome = behaviour[store.slug]
        if isinstance(outcome, Exception):
            raise outcome
        yield from outcome

    read.calls = calls
    return read


def test_all_stores_ok():
    sink = RecordingSink()
    reader = reader_from({"a": [product(A)], "b": [product(B), product(B, "2")]})
    results = run_stores([A, B], client=None, readers={"fake": reader}, sink=sink)
    assert [(r.slug, r.ok, r.products_seen) for r in results] == [("a", True, 1), ("b", True, 2)]
    assert sink.events == [
        ("started", "a"), ("succeeded", "a", 1),
        ("started", "b"), ("succeeded", "b", 2),
    ]


def test_failing_store_does_not_stop_others():
    sink = RecordingSink()
    reader = reader_from({"a": FetchError("boom"), "b": [product(B)]})
    results = run_stores([A, B], client=None, readers={"fake": reader}, sink=sink)
    assert [r.ok for r in results] == [False, True]
    assert results[0].error == "boom"
    assert ("failed", "a", "boom") in sink.events
    assert ("succeeded", "b", 1) in sink.events


def test_zero_products_counts_as_failure():
    sink = RecordingSink()
    results = run_stores([A], client=None, readers={"fake": reader_from({"a": []})}, sink=sink)
    assert (results[0].ok, results[0].error) == (False, "no products returned")
    assert sink.events == [("started", "a"), ("failed", "a", "no products returned")]


def test_sink_failure_counts_as_store_failure():
    class BrokenSink(RecordingSink):
        def store_succeeded(self, store, products):
            raise RuntimeError("database went away")

    sink = BrokenSink()
    results = run_stores([A], client=None, readers={"fake": reader_from({"a": [product(A)]})}, sink=sink)
    assert results[0].ok is False
    assert ("failed", "a", "database went away") in sink.events


@pytest.fixture
def env(tmp_path, monkeypatch):
    path = tmp_path / "stores.yaml"
    path.write_text(STORES_YAML, encoding="utf-8")
    return {"STORES_FILE": str(path), "REQUESTS_PER_SECOND": "1000"}


def install_reader(monkeypatch, behaviour):
    reader = reader_from(behaviour)
    monkeypatch.setitem(platforms.READERS, "fake", reader)
    return reader


def test_main_dry_run_prints_json(env, monkeypatch, capsys):
    install_reader(monkeypatch, {"a": [product(A)], "b": [product(B)]})
    assert main(["run", "--dry-run"], env) == 0
    lines = capsys.readouterr().out.splitlines()
    products = [json.loads(line) for line in lines if line.startswith("{")]
    assert len(products) == 2
    assert products[0]["price"] == "1490.00"
    assert products[0]["store_slug"] == "a"
    assert "raw" not in products[0]
    assert any(line.startswith("event=run_finished") and "ok=2" in line for line in lines)


def test_main_store_filter(env, monkeypatch):
    reader = install_reader(monkeypatch, {"a": [product(A)], "b": [product(B)]})
    assert main(["run", "--dry-run", "--store", "b"], env) == 0
    assert reader.calls == ["b"]


def test_main_returns_1_when_a_store_fails(env, monkeypatch):
    install_reader(monkeypatch, {"a": FetchError("down"), "b": [product(B)]})
    assert main(["run", "--dry-run"], env) == 1


def test_unknown_store_slug(env, monkeypatch, capsys):
    reader = install_reader(monkeypatch, {"a": [product(A)], "b": [product(B)]})
    assert main(["run", "--dry-run", "--store", "nope"], env) == 2
    out = capsys.readouterr().out
    assert "event=config_error" in out
    assert "nope" in out
    assert reader.calls == []


def test_main_requires_database_url(env, monkeypatch, capsys):
    install_reader(monkeypatch, {"a": [product(A)], "b": [product(B)]})
    assert main(["run"], env) == 2
    assert "DATABASE_URL" in capsys.readouterr().out


def test_log_quotes_values_with_spaces(capsys):
    from scraper.run import log

    log("store_failed", slug="a", error="connection reset by peer")
    assert capsys.readouterr().out.strip() == 'event=store_failed slug=a error="connection reset by peer"'
