import copy
import json
from decimal import Decimal
from pathlib import Path

from scraper.models import StoreConfig
from scraper.platforms import READERS
from scraper.platforms import shopify

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "shopify_products.json").read_text(encoding="utf-8")
)
STORE = StoreConfig(slug="kaboa", name="Kaboa", url="https://www.kaboa.com.uy", platform="shopify")


class FakeClient:
    """Returns payloads by URL and records what was requested."""

    def __init__(self, pages=None, default=None):
        self.pages = pages or {}
        self.default = default
        self.requested: list[str] = []

    def get_json(self, url):
        self.requested.append(url)
        if url in self.pages:
            return self.pages[url]
        if self.default is not None:
            return self.default
        return {"products": []}


def raw(index=0, **changes):
    product = copy.deepcopy(FIXTURE["products"][index])
    product.update(changes)
    return product


def listing(page, collection=None):
    base = STORE.url if collection is None else f"{STORE.url}/collections/{collection}"
    return f"{base}/products.json?limit=250&page={page}"


def test_parse_basic_fields():
    product = shopify.parse_product(STORE, raw())
    assert product.store_slug == "kaboa"
    assert product.external_id == "15291699429629"
    assert product.title == "Buzo Retro"
    assert product.url == "https://www.kaboa.com.uy/products/buzo-retro"
    assert product.currency == "UYU"
    assert product.vendor == "Kaboa.ind"
    assert product.product_type is None
    assert product.image_urls == [
        "https://cdn.shopify.com/s/files/1/retro-front.jpg",
        "https://cdn.shopify.com/s/files/1/retro-back.jpg",
    ]
    assert product.raw["id"] == 15291699429629


def test_parse_price_sizes_stock():
    product = shopify.parse_product(STORE, raw())
    assert product.price == Decimal("1490.00")
    assert product.sizes == ["M", "L"]
    assert product.in_stock is True


def test_price_falls_back_to_lowest_when_none_available():
    product_raw = raw()
    for variant in product_raw["variants"]:
        variant["available"] = False
    product = shopify.parse_product(STORE, product_raw)
    assert product.price == Decimal("1290.00")
    assert product.in_stock is False
    assert product.sizes == []


def test_size_option_name_match():
    for name in ("Talle", "TALLA", "Size", "Tamaño"):
        product_raw = raw()
        product_raw["options"][0]["name"] = name
        assert shopify.parse_product(STORE, product_raw).sizes == ["M", "L"], name
    assert shopify.parse_product(STORE, raw(1)).sizes == []


def test_size_in_second_option():
    product_raw = raw()
    product_raw["options"] = [
        {"name": "Color", "position": 1, "values": ["Negro"]},
        {"name": "Talle", "position": 2, "values": ["S", "M"]},
    ]
    product_raw["variants"] = [
        {"id": 1, "option1": "Negro", "option2": "S", "price": "100.00", "available": True},
        {"id": 2, "option1": "Negro", "option2": "M", "price": "100.00", "available": True},
    ]
    assert shopify.parse_product(STORE, product_raw).sizes == ["S", "M"]


def test_product_without_variants():
    product = shopify.parse_product(STORE, raw(variants=[]))
    assert product.price is None
    assert product.in_stock is False
    assert product.sizes == []


def test_unparseable_price_is_skipped():
    product_raw = raw()
    product_raw["variants"][2]["price"] = "consultar"
    product = shopify.parse_product(STORE, product_raw)
    assert product.price == Decimal("1590.00")


def test_tags_string_and_list():
    as_string = shopify.parse_product(STORE, raw(tags="oversize, negro"))
    as_list = shopify.parse_product(STORE, raw(tags=["oversize", "negro"]))
    empty = shopify.parse_product(STORE, raw(tags=""))
    assert as_string.tags == ["oversize", "negro"]
    assert as_list.tags == ["oversize", "negro"]
    assert empty.tags == []


def test_paginates_until_empty_page():
    client = FakeClient(
        {
            listing(1): {"products": [raw(0)]},
            listing(2): {"products": [raw(1)]},
            listing(3): {"products": []},
        }
    )
    products = list(shopify.fetch_products(STORE, client))
    assert [p.title for p in products] == ["Buzo Retro", "Gorro Industrial"]
    assert client.requested == [listing(1), listing(2), listing(3)]


def test_stops_after_100_pages():
    counter = iter(range(10_000))

    class EndlessClient(FakeClient):
        def get_json(self, url):
            self.requested.append(url)
            return {"products": [raw(0, id=next(counter))]}

    client = EndlessClient()
    products = list(shopify.fetch_products(STORE, client))
    assert len(client.requested) == 100
    assert len(products) == 100


def test_uses_collection_urls_for_mixed_store():
    store = StoreConfig(
        slug="mix", name="Mix", url="https://mix.uy", platform="shopify",
        audience="mixed", collections=("hombre",),
    )
    client = FakeClient({"https://mix.uy/collections/hombre/products.json?limit=250&page=1": {"products": [raw(0)]}})
    products = list(shopify.fetch_products(store, client))
    assert len(products) == 1
    assert all("/collections/hombre/products.json" in url for url in client.requested)


def test_dedupes_products_across_collections():
    store = StoreConfig(
        slug="mix", name="Mix", url="https://mix.uy", platform="shopify",
        audience="mixed", collections=("hombre", "nuevo"),
    )
    client = FakeClient(
        {
            "https://mix.uy/collections/hombre/products.json?limit=250&page=1": {"products": [raw(0)]},
            "https://mix.uy/collections/nuevo/products.json?limit=250&page=1": {"products": [raw(0), raw(1)]},
        }
    )
    products = list(shopify.fetch_products(store, client))
    assert [p.external_id for p in products] == ["15291699429629", "15292122726653"]


def test_reader_registered():
    assert READERS["shopify"] is shopify.fetch_products
