import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from scraper.models import Product

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL not set")

T0 = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=6)


@pytest.fixture
def conn():
    from scraper import db

    connection = db.connect(DATABASE_URL)
    db.apply_schema(connection)
    connection.execute("TRUNCATE products, scrape_runs RESTART IDENTITY")
    connection.commit()
    yield connection
    connection.rollback()
    connection.close()


def product(external_id="1", store="kaboa", price="1490.00", **changes):
    fields = dict(
        store_slug=store,
        external_id=external_id,
        title=f"Buzo {external_id}",
        url=f"https://www.kaboa.com.uy/products/buzo-{external_id}",
        price=Decimal(price),
        currency="UYU",
        sizes=["M", "L"],
        in_stock=True,
        image_urls=["https://cdn.shopify.com/a.jpg"],
        vendor="Kaboa.ind",
        product_type=None,
        tags=["oversize"],
        raw={"id": external_id},
    )
    fields.update(changes)
    return Product(**fields)


def rows(conn, store="kaboa"):
    return conn.execute(
        "SELECT external_id, price, first_seen_at, last_seen_at, removed_at, sizes, raw "
        "FROM products WHERE store_slug = %s ORDER BY external_id",
        (store,),
    ).fetchall()


def test_apply_schema_twice(conn):
    from scraper import db

    db.apply_schema(conn)
    db.apply_schema(conn)


def test_upsert_inserts_then_updates(conn):
    from scraper import db

    assert db.upsert_products(conn, [product(price="1490.00")], T0) == 1
    db.upsert_products(conn, [product(price="1290.00")], T1)
    [row] = rows(conn)
    assert row[1] == Decimal("1290.00")
    assert row[2] == T0
    assert row[3] == T1
    assert row[5] == ["M", "L"]
    assert row[6] == {"id": "1"}


def test_mark_removed_only_unseen(conn):
    from scraper import db

    db.upsert_products(conn, [product("A"), product("B")], T0)
    db.upsert_products(conn, [product("A")], T1)
    assert db.mark_removed(conn, "kaboa", T1) == 1
    by_id = {r[0]: r[4] for r in rows(conn)}
    assert by_id["A"] is None
    assert by_id["B"] is not None


def test_product_returns_after_removal(conn):
    from scraper import db

    db.upsert_products(conn, [product("A")], T0)
    db.mark_removed(conn, "kaboa", T1)
    db.upsert_products(conn, [product("A")], T1 + timedelta(hours=6))
    assert rows(conn)[0][4] is None


def test_failed_run_marks_nothing(conn):
    from scraper import db

    db.upsert_products(conn, [product("A"), product("B")], T0)
    run_id, started_at = db.start_run(conn, "kaboa")
    db.finish_run(conn, run_id, "failed", 0, "boom")
    assert all(r[4] is None for r in rows(conn))
    status, error, finished = conn.execute(
        "SELECT status, error, finished_at FROM scrape_runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert (status, error) == ("failed", "boom")
    assert finished is not None


def test_start_run_records_running(conn):
    from scraper import db

    run_id, started_at = db.start_run(conn, "kaboa")
    status, stored_start = conn.execute(
        "SELECT status, started_at FROM scrape_runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert status == "running"
    assert stored_start == started_at


def test_mark_removed_scoped_to_store(conn):
    from scraper import db

    db.upsert_products(conn, [product("A"), product("X", store="other")], T0)
    db.mark_removed(conn, "kaboa", T1)
    assert rows(conn, "other")[0][4] is None


def test_product_without_price(conn):
    from scraper import db

    no_price = product("C")
    no_price.price = None
    db.upsert_products(conn, [no_price], T0)
    assert rows(conn)[0][1] is None


def test_db_sink_saves_and_removes(conn):
    from scraper.run import DbSink, run_stores
    from scraper.models import StoreConfig

    store = StoreConfig(slug="kaboa", name="Kaboa", url="https://www.kaboa.com.uy", platform="fake")
    batches = iter([[product("A"), product("B")], [product("A")]])
    readers = {"fake": lambda s, c: iter(next(batches))}

    run_stores([store], None, readers, DbSink(conn))
    run_stores([store], None, readers, DbSink(conn))

    by_id = {r[0]: r[4] for r in rows(conn)}
    assert by_id["A"] is None and by_id["B"] is not None
    statuses = conn.execute("SELECT status, products_seen FROM scrape_runs ORDER BY id").fetchall()
    assert statuses == [("ok", 2), ("ok", 1)]


def test_db_sink_failure_rolls_back_and_records(conn):
    from scraper.http import FetchError
    from scraper.run import DbSink, run_stores
    from scraper.models import StoreConfig

    store = StoreConfig(slug="kaboa", name="Kaboa", url="https://www.kaboa.com.uy", platform="fake")
    db_products = [product("A")]
    run_stores([store], None, {"fake": lambda s, c: iter(db_products)}, DbSink(conn))

    def half_then_fail(s, c):
        yield product("A", price="1.00")
        raise FetchError("page 2 timed out")

    run_stores([store], None, {"fake": half_then_fail}, DbSink(conn))

    [row] = rows(conn)
    assert row[1] == Decimal("1490.00")
    assert row[4] is None
    last = conn.execute("SELECT status, error FROM scrape_runs ORDER BY id DESC LIMIT 1").fetchone()
    assert last == ("failed", "page 2 timed out")
