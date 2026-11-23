"""One reader per e-commerce platform, looked up by the name used in stores.yaml."""

from collections.abc import Callable, Iterator
from typing import Any

from scraper.models import Product, StoreConfig
from scraper.platforms import shopify

Reader = Callable[[StoreConfig, Any], Iterator[Product]]

READERS: dict[str, Reader] = {
    "shopify": shopify.fetch_products,
}
