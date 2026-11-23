from web import catalog
from web.catalog import Filters


def titles(conn, **kwargs):
    return [p["title"] for p in catalog.search(conn, Filters(**kwargs)).items]


def test_hides_removed_and_orders_newest_first(conn):
    result = catalog.search(conn, Filters())
    assert result.total == 6
    assert "Campera Vieja" not in [p["title"] for p in result.items]
    assert result.items[0]["title"] == "Buzo Retro"
    assert result.items[0]["is_new"] is True
    assert result.items[0]["image"] == "https://cdn.shopify.com/kaboa-1.jpg?v=1"


def test_search_words_all_must_match(conn):
    assert titles(conn, q="remera") == ["Remera Anime", "Remera Oversize Negra"]
    assert titles(conn, q="remera negra") == ["Remera Oversize Negra"]
    assert titles(conn, q="REMERA") == ["Remera Anime", "Remera Oversize Negra"]


def test_search_treats_wildcards_as_text(conn):
    assert titles(conn, q="100%") == ["Canguro Gamer 100%"]
    assert titles(conn, q="%") == ["Canguro Gamer 100%"]
    assert titles(conn, q="_") == []


def test_search_matches_store_brand(conn):
    assert len(titles(conn, q="ramon")) == 2


def test_category(conn):
    assert sorted(titles(conn, cat="buzos")) == ["Buzo Industrial", "Buzo Retro", "Canguro Gamer 100%"]
    assert titles(conn, cat="pantalones") == ["Pantalón Barrel"]


def test_store_size_stock_and_price(conn):
    assert len(titles(conn, stores=("ramon",))) == 2
    assert sorted(titles(conn, sizes=("M",))) == ["Buzo Retro", "Remera Anime", "Remera Oversize Negra"]
    assert "Buzo Industrial" not in titles(conn, in_stock=True)
    assert titles(conn, min_price=1000, max_price=2000, sort="precio_asc") == ["Buzo Retro", "Buzo Industrial"]


def test_price_sort_puts_missing_prices_last(conn):
    assert titles(conn, sort="precio_asc")[0] == "Remera Oversize Negra"
    assert titles(conn, sort="precio_asc")[-1] == "Canguro Gamer 100%"
    assert titles(conn, sort="precio_desc")[0] == "Pantalón Barrel"
    assert titles(conn, sort="precio_desc")[-1] == "Canguro Gamer 100%"


def test_page_past_the_end_is_clamped(conn):
    result = catalog.search(conn, Filters(page=99))
    assert (result.page, result.pages, len(result.items)) == (1, 1, 6)


def test_pagination(conn, monkeypatch):
    monkeypatch.setattr(catalog, "PAGE_SIZE", 4)
    first, second = catalog.search(conn, Filters()), catalog.search(conn, Filters(page=2))
    assert (first.pages, len(first.items), len(second.items)) == (2, 4, 2)
    assert not {p["id"] for p in first.items} & {p["id"] for p in second.items}


def test_get_product_and_related(conn):
    product = catalog.get_product(conn, 1)
    assert product["title"] == "Buzo Retro" and product["removed"] is False
    assert len(product["image_urls"]) == 2
    assert catalog.get_product(conn, 5)["removed"] is True
    assert catalog.get_product(conn, 999) is None
    others = catalog.related(conn, product)
    assert {p["store_slug"] for p in others} == {"kaboa"}
    assert "Buzo Retro" not in [p["title"] for p in others]
    assert "Campera Vieja" not in [p["title"] for p in others]
    assert others[-1]["title"] == "Buzo Industrial"  # out of stock goes last


def test_store_stats_and_sizes(conn):
    stats = {s["slug"]: (s["total"], s["in_stock"]) for s in catalog.store_stats(conn)}
    assert stats == {"kaboa": (4, 3), "ramon": (2, 2)}
    assert catalog.size_options(conn) == ["S", "M", "L", "XL", "42", "44"]


def put_on_sale(conn, title, was):
    conn.execute(
        "UPDATE products SET raw = jsonb_build_object('variants', jsonb_build_array("
        "jsonb_build_object('compare_at_price', %s::text), jsonb_build_object('compare_at_price', null))) "
        "WHERE title = %s", (was, title),
    )
    conn.commit()


def test_sale_price_comes_from_the_stores_compare_at_price(conn):
    put_on_sale(conn, "Buzo Retro", "3336.00")
    put_on_sale(conn, "Remera Anime", "990.00")       # same as the price: not a sale
    put_on_sale(conn, "Pantalón Barrel", "consultar")  # not a number: ignored
    by_title = {p["title"]: p for p in catalog.search(conn, Filters()).items}
    assert by_title["Buzo Retro"]["was_price"] == 3336
    assert by_title["Buzo Retro"]["discount"] == 50
    assert by_title["Remera Anime"]["was_price"] is None
    assert by_title["Pantalón Barrel"]["was_price"] is None
    assert by_title["Buzo Industrial"]["discount"] is None


def test_on_sale_filter(conn):
    put_on_sale(conn, "Buzo Retro", "3336.00")
    assert titles(conn, on_sale=True) == ["Buzo Retro"]
    product = catalog.get_product(conn, catalog.search(conn, Filters(on_sale=True)).items[0]["id"])
    assert product["was_price"] == 3336 and product["discount"] == 50
