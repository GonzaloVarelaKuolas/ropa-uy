"""Runs the readers for each store and hands the products to a sink."""

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from scraper import db
from scraper.models import Product, StoreConfig
from scraper.platforms import Reader


def log(event: str, **fields: Any) -> None:
    """One line per event, key=value, so `kubectl logs` reads well."""
    parts = [f"event={event}"]
    for key, value in fields.items():
        text = str(value)
        if not text or any(ch in text for ch in ' ="'):
            text = json.dumps(text, ensure_ascii=False)
        parts.append(f"{key}={text}")
    print(" ".join(parts), flush=True)


class Sink(Protocol):
    def store_started(self, store: StoreConfig) -> None: ...
    def store_succeeded(self, store: StoreConfig, products: list[Product]) -> None: ...
    def store_failed(self, store: StoreConfig, error: str) -> None: ...


class PrintSink:
    """--dry-run: prints products as JSON lines instead of saving them."""

    def store_started(self, store: StoreConfig) -> None:
        pass

    def store_succeeded(self, store: StoreConfig, products: list[Product]) -> None:
        for product in products:
            data = asdict(product)
            data.pop("raw")
            print(json.dumps(data, default=_json_default, ensure_ascii=False), flush=True)

    def store_failed(self, store: StoreConfig, error: str) -> None:
        pass


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


class DbSink:
    """Saves each store's products in one transaction, committed only on success."""

    def __init__(self, conn):
        self.conn = conn
        self._run_id: int | None = None
        self._started_at: datetime | None = None

    def store_started(self, store: StoreConfig) -> None:
        self._run_id, self._started_at = db.start_run(self.conn, store.slug)
        self.conn.commit()

    def store_succeeded(self, store: StoreConfig, products: list[Product]) -> None:
        db.upsert_products(self.conn, products, self._started_at)
        removed = db.mark_removed(self.conn, store.slug, self._started_at)
        db.finish_run(self.conn, self._run_id, "ok", len(products), None)
        self.conn.commit()
        log("store_saved", slug=store.slug, products=len(products), removed=removed)

    def store_failed(self, store: StoreConfig, error: str) -> None:
        self.conn.rollback()
        if self._run_id is not None:
            db.finish_run(self.conn, self._run_id, "failed", 0, error)
            self.conn.commit()


@dataclass
class StoreResult:
    slug: str
    ok: bool
    products_seen: int
    error: str | None


def run_stores(
    stores: list[StoreConfig], client: Any, readers: Mapping[str, Reader], sink: Sink
) -> list[StoreResult]:
    results = []
    for store in stores:
        log("store_started", slug=store.slug, platform=store.platform)
        sink.store_started(store)
        try:
            products = list(readers[store.platform](store, client))
            if not products:
                raise RuntimeError("no products returned")
            sink.store_succeeded(store, products)
        except Exception as exc:  # one bad store must not stop the others
            error = str(exc) or type(exc).__name__
            log("store_failed", slug=store.slug, error=error)
            sink.store_failed(store, error)
            results.append(StoreResult(store.slug, False, 0, error))
        else:
            log("store_finished", slug=store.slug, products=len(products))
            results.append(StoreResult(store.slug, True, len(products), None))
    return results
