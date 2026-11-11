"""Reads products from Shopify stores through their public products.json feed."""

import re
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from scraper.models import Product, StoreConfig

PAGE_SIZE = 250
MAX_PAGES = 100
SIZE_OPTION = re.compile(r"talle|talla|size|tamaño", re.IGNORECASE)


class JsonClient(Protocol):
    def get_json(self, url: str) -> Any: ...


def fetch_products(store: StoreConfig, client: JsonClient) -> Iterator[Product]:
    """Yields every product once, across all pages and configured collections.

    A RobotsDisallowed or FetchError from the client is not caught here: the
    store fails for this run, which is safer than a partial catalog.
    """
    seen: set[str] = set()
    for base in _listing_bases(store):
        for page in range(1, MAX_PAGES + 1):
            payload = client.get_json(f"{base}/products.json?limit={PAGE_SIZE}&page={page}")
            items = (payload.get("products") or []) if isinstance(payload, dict) else []
            if not items:
                break
            for item in items:
                product = parse_product(store, item)
                if product.external_id not in seen:
                    seen.add(product.external_id)
                    yield product


def _listing_bases(store: StoreConfig) -> list[str]:
    if not store.collections:
        return [store.url]
    return [f"{store.url}/collections/{handle}" for handle in store.collections]


def parse_product(store: StoreConfig, raw: dict) -> Product:
    variants = raw.get("variants") or []
    available = [v for v in variants if v.get("available")]
    priced_pool = available or variants
    prices = [p for p in (_price(v) for v in priced_pool) if p is not None]

    return Product(
        store_slug=store.slug,
        external_id=str(raw["id"]),
        title=str(raw.get("title") or ""),
        url=f"{store.url}/products/{raw.get('handle', '')}",
        price=min(prices) if prices else None,
        currency=store.currency,
        sizes=_available_sizes(raw.get("options") or [], available),
        in_stock=bool(available),
        image_urls=[img["src"] for img in raw.get("images") or [] if img.get("src")],
        vendor=raw.get("vendor") or None,
        product_type=raw.get("product_type") or None,
        tags=_tags(raw.get("tags")),
        raw=raw,
    )


def _price(variant: dict) -> Decimal | None:
    try:
        return Decimal(str(variant.get("price")))
    except (InvalidOperation, ValueError):
        return None


def _available_sizes(options: list[dict], available: list[dict]) -> list[str]:
    for index, option in enumerate(options):
        if SIZE_OPTION.search(str(option.get("name", ""))):
            key = f"option{index + 1}"
            in_stock = {v.get(key) for v in available}
            return [value for value in option.get("values") or [] if value in in_stock]
    return []


def _tags(value: object) -> list[str]:
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, list):
        items = value
    else:
        return []
    return [str(tag).strip() for tag in items if str(tag).strip()]
