import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Jsonb

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
SCHEMA = Path(__file__).parents[2] / "scraper" / "scraper" / "schema.sql"
NOW = datetime.now(timezone.utc)

# (store, id, title, price, sizes, in_stock, days_old, removed)
PRODUCTS = [
    ("kaboa", "1", "Buzo Retro", "1668.00", ["S", "M", "L"], True, 1, False),
    ("kaboa", "2", "Buzo Industrial", "1890.00", [], False, 30, False),
    ("kaboa", "3", "Remera Oversize Negra", "890.00", ["M", "XL"], True, 30, False),
    ("kaboa", "4", "Pantalón Barrel", "2490.00", ["42", "44"], True, 30, False),
    ("kaboa", "5", "Campera Vieja", "3990.00", ["L"], True, 60, True),
    ("ramon", "1", "Remera Anime", "990.00", ["S", "M"], True, 2, False),
    ("ramon", "2", "Canguro Gamer 100%", None, ["L"], True, 40, False),
]


@pytest.fixture
def conn():
    if not DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(SCHEMA.read_text(encoding="utf-8"))
        connection.execute("TRUNCATE products, scrape_runs RESTART IDENTITY CASCADE")
        for store, ext, title, price, sizes, stock, age, removed in PRODUCTS:
            seen = NOW - timedelta(days=age)
            connection.execute(
                "INSERT INTO products (store_slug, external_id, title, url, price, currency, sizes, "
                "in_stock, image_urls, vendor, tags, raw, first_seen_at, last_seen_at, removed_at) "
                "VALUES (%s,%s,%s,%s,%s,'UYU',%s,%s,%s,%s,'{}',%s,%s,%s,%s)",
                (store, ext, title, f"https://{store}.uy/products/{ext}", price, sizes, stock,
                 [f"https://cdn.shopify.com/{store}-{ext}.jpg?v=1", f"https://cdn.shopify.com/{store}-{ext}-b.jpg?v=1"],
                 store.title(), Jsonb({}), seen, NOW, NOW if removed else None),
            )
        connection.commit()
    with psycopg.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row) as connection:
        yield connection


@pytest.fixture
def client(conn, tmp_path):
    from fastapi.testclient import TestClient

    from web.app import create_app

    stores = tmp_path / "stores.yaml"
    stores.write_text(
        "stores:\n  - slug: kaboa\n    name: Kaboa\n    url: https://www.kaboa.com.uy\n    platform: shopify\n",
        encoding="utf-8",
    )
    return TestClient(create_app(DATABASE_URL, str(stores)))
