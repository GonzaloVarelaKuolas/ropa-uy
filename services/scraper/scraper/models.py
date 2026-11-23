"""Data shapes shared by every part of the scraper."""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class StoreConfig:
    """One store from stores.yaml."""

    slug: str
    name: str
    url: str
    platform: str
    currency: str = "UYU"
    audience: str = "unisex"
    collections: tuple[str, ...] = ()


@dataclass
class Product:
    """One product, in the same format whatever platform it came from."""

    store_slug: str
    external_id: str
    title: str
    url: str
    price: Decimal | None
    currency: str
    sizes: list[str] = field(default_factory=list)
    in_stock: bool = False
    image_urls: list[str] = field(default_factory=list)
    vendor: str | None = None
    product_type: str | None = None
    tags: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)
