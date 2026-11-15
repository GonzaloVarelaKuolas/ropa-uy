from starlette.datastructures import QueryParams

from web.catalog import CATEGORIES, Filters, format_price, thumb


def parse(query):
    return Filters.from_query(QueryParams(query))


def test_defaults():
    f = parse("")
    assert f == Filters()
    assert (f.sort, f.page, f.in_stock) == ("nuevo", 1, False)
    assert not f.is_filtered


def test_parses_everything():
    f = parse("q=buzo+negro&cat=buzos&tienda=kaboa&tienda=otra&talle=M&talle=XL&min=500&max=2000&stock=1&orden=precio_asc&pagina=3")
    assert f == Filters(
        q="buzo negro", cat="buzos", stores=("kaboa", "otra"), sizes=("M", "XL"),
        min_price=500, max_price=2000, in_stock=True, sort="precio_asc", page=3,
    )
    assert f.is_filtered


def test_bad_values_fall_back_to_defaults():
    f = parse("cat=nope&min=abc&max=-5&orden=hack&pagina=0&q=+++")
    assert f == Filters()


def test_swapped_price_range_is_fixed():
    f = parse("min=3000&max=1000")
    assert (f.min_price, f.max_price) == (1000, 3000)


def test_long_search_is_trimmed():
    assert len(parse("q=" + "a" * 500).q) == 80


def test_to_query_omits_defaults_and_round_trips():
    f = parse("q=buzo&tienda=kaboa&talle=M&stock=1&pagina=2")
    assert Filters().to_query() == ""
    assert parse(f.to_query()) == f


def test_to_query_with_changes_resets_page_unless_given():
    f = parse("q=buzo&pagina=4")
    assert parse(f.to_query(cat="buzos")) == Filters(q="buzo", cat="buzos", page=1)
    assert parse(f.to_query(page=5)).page == 5


def test_without_removes_one_value():
    f = parse("tienda=a&tienda=b&talle=M")
    assert f.without("stores", "a").stores == ("b",)
    assert f.without("sizes", "M").sizes == ()


def test_category_patterns():
    import re

    def cat_of(title):
        return [slug for slug, c in CATEGORIES.items() if re.search(c.pattern.replace(r"\m", r"\b").replace(r"\M", r"\b"), title, re.I)]

    assert cat_of("Buzo Retro") == ["buzos"]
    assert cat_of("Remera Oversize Negra") == ["remeras"]
    assert cat_of("Camiseta Fútbol N+") == ["remeras"]
    assert cat_of("Camisa Lino") == ["camisas"]
    assert cat_of("Pantalón Barrel") == ["pantalones"]
    assert cat_of("Campera Balaclava") == ["camperas"]
    assert cat_of("Pack Boxer x3") == ["accesorios"]
    assert cat_of("Canguro Capucha") == ["buzos"]


def test_format_price():
    from decimal import Decimal

    assert format_price(Decimal("1668.00")) == "$ 1.668"
    assert format_price(Decimal("490")) == "$ 490"
    assert format_price(Decimal("12999.50")) == "$ 12.999,50"
    assert format_price(None) == "Consultar"


def test_thumb_only_touches_shopify():
    assert thumb("https://cdn.shopify.com/a.jpg?v=1", 600) == "https://cdn.shopify.com/a.jpg?v=1&width=600"
    assert thumb("https://cdn.shopify.com/a.jpg", 600) == "https://cdn.shopify.com/a.jpg?width=600"
    assert thumb("https://other.uy/a.jpg", 600) == "https://other.uy/a.jpg"


def test_on_sale_round_trips():
    f = parse("oferta=1")
    assert f.on_sale and f.is_filtered
    assert f.to_query() == "oferta=1"
    assert not parse("oferta=si").on_sale
