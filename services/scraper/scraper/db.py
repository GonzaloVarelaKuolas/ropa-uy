"""PostgreSQL storage. None of these functions commit: the caller decides."""

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from scraper.models import Product

SCHEMA_FILE = Path(__file__).with_name("schema.sql")

UPSERT = """
INSERT INTO products (
    store_slug, external_id, title, url, price, currency, sizes, in_stock,
    image_urls, vendor, product_type, tags, raw, first_seen_at, last_seen_at, removed_at
) VALUES (
    %(store_slug)s, %(external_id)s, %(title)s, %(url)s, %(price)s, %(currency)s, %(sizes)s,
    %(in_stock)s, %(image_urls)s, %(vendor)s, %(product_type)s, %(tags)s, %(raw)s,
    %(seen_at)s, %(seen_at)s, NULL
)
ON CONFLICT (store_slug, external_id) DO UPDATE SET
    title = EXCLUDED.title,
    url = EXCLUDED.url,
    price = EXCLUDED.price,
    currency = EXCLUDED.currency,
    sizes = EXCLUDED.sizes,
    in_stock = EXCLUDED.in_stock,
    image_urls = EXCLUDED.image_urls,
    vendor = EXCLUDED.vendor,
    product_type = EXCLUDED.product_type,
    tags = EXCLUDED.tags,
    raw = EXCLUDED.raw,
    last_seen_at = EXCLUDED.last_seen_at,
    removed_at = NULL
"""


def connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url)


def apply_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))


def start_run(conn: psycopg.Connection, store_slug: str) -> tuple[int, datetime]:
    row = conn.execute(
        "INSERT INTO scrape_runs (store_slug, status) VALUES (%s, 'running') "
        "RETURNING id, started_at",
        (store_slug,),
    ).fetchone()
    return row[0], row[1]


def upsert_products(conn: psycopg.Connection, products: Iterable[Product], seen_at: datetime) -> int:
    params = [
        {
            "store_slug": p.store_slug,
            "external_id": p.external_id,
            "title": p.title,
            "url": p.url,
            "price": p.price,
            "currency": p.currency,
            "sizes": p.sizes,
            "in_stock": p.in_stock,
            "image_urls": p.image_urls,
            "vendor": p.vendor,
            "product_type": p.product_type,
            "tags": p.tags,
            "raw": Jsonb(p.raw),
            "seen_at": seen_at,
        }
        for p in products
    ]
    if params:
        with conn.cursor() as cur:
            cur.executemany(UPSERT, params)
    return len(params)


def mark_removed(conn: psycopg.Connection, store_slug: str, run_started_at: datetime) -> int:
    cur = conn.execute(
        "UPDATE products SET removed_at = now() "
        "WHERE store_slug = %s AND last_seen_at < %s AND removed_at IS NULL",
        (store_slug, run_started_at),
    )
    return cur.rowcount


def finish_run(
    conn: psycopg.Connection, run_id: int, status: str, products_seen: int, error: str | None
) -> None:
    conn.execute(
        "UPDATE scrape_runs SET status = %s, products_seen = %s, error = %s, finished_at = now() "
        "WHERE id = %s",
        (status, products_seen, error, run_id),
    )
