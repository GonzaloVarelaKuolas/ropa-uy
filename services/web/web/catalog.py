"""The catalog: what visitors can filter by, and the queries behind each page.

Read-only. The scraper owns the tables; this module only SELECTs from them.
"""

import math
import re
from dataclasses import dataclass, replace
from decimal import Decimal
from urllib.parse import urlencode

import psycopg

PAGE_SIZE = 48
MAX_QUERY_LENGTH = 80
MAX_QUERY_WORDS = 6


@dataclass(frozen=True)
class Category:
    label: str
    pattern: str  # PostgreSQL regex, matched case-insensitively against the title


# Stores rarely fill in a product type, so categories come from the title.
# \m and \M are PostgreSQL's "start of word" and "end of word".
CATEGORIES: dict[str, Category] = {
    "remeras": Category("Remeras", r"\m(remera|camiseta|musculosa|polo|tee|t-?shirt)"),
    "buzos": Category("Buzos", r"\m(buzo|canguro|hoodie|sweater|su[eé]ter|polar)"),
    "camperas": Category("Camperas", r"\m(campera|chaqueta|chaleco|parka|rompeviento|abrigo|jacket)"),
    "camisas": Category("Camisas", r"\mcamisas?\M"),
    "pantalones": Category("Pantalones", r"\m(pantal[oó]n|jean|jogger|cargo|chino|babucha)"),
    "shorts": Category("Shorts", r"\m(short|bermuda|malla)"),
    "calzado": Category("Calzado", r"\m(zapatilla|champi[oó]n|bota|zapato|sandalia|ojota)"),
    "accesorios": Category(
        "Accesorios",
        r"\m(gorr[oa]s?|caps?|medias?|boxers?|cintur[oó]n|mochila|ri[ñn]onera|bufanda|lentes|billetera|bolso|pack)\M",
    ),
}

SORTS: dict[str, tuple[str, str]] = {
    "nuevo": ("Lo más nuevo", "in_stock DESC, first_seen_at DESC, id DESC"),  # sold-out items go last
    "precio_asc": ("Precio: menor a mayor", "price ASC NULLS LAST, id DESC"),
    "precio_desc": ("Precio: mayor a menor", "price DESC NULLS LAST, id DESC"),
}

SIZE_ORDER = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "2XL", "XXXL", "3XL", "4XL", "5XL"]


def _positive_int(value: str | None) -> int | None:
    try:
        number = int(value or "")
    except ValueError:
        return None
    return number if number > 0 else None


@dataclass(frozen=True)
class Filters:
    """What the visitor asked for, parsed from the URL. Invalid values become defaults."""

    q: str = ""
    cat: str = ""
    stores: tuple[str, ...] = ()
    sizes: tuple[str, ...] = ()
    min_price: int | None = None
    max_price: int | None = None
    in_stock: bool = False
    on_sale: bool = False
    sort: str = "nuevo"
    page: int = 1

    @classmethod
    def from_query(cls, params) -> "Filters":
        """params: anything with .get(name) and .getlist(name), like Starlette's QueryParams."""
        q = " ".join((params.get("q") or "").split())[:MAX_QUERY_LENGTH]
        cat = params.get("cat") or ""
        sort = params.get("orden") or "nuevo"
        low, high = _positive_int(params.get("min")), _positive_int(params.get("max"))
        if low and high and low > high:
            low, high = high, low
        return cls(
            q=q,
            cat=cat if cat in CATEGORIES else "",
            stores=tuple(dict.fromkeys(s for s in params.getlist("tienda") if s))[:30],
            sizes=tuple(dict.fromkeys(s for s in params.getlist("talle") if s))[:30],
            min_price=low,
            max_price=high,
            in_stock=params.get("stock") == "1",
            on_sale=params.get("oferta") == "1",
            sort=sort if sort in SORTS else "nuevo",
            page=_positive_int(params.get("pagina")) or 1,
        )

    @property
    def is_filtered(self) -> bool:
        return replace(self, sort="nuevo", page=1) != Filters()

    def to_query(self, **changes) -> str:
        """The URL query for these filters. Changing a filter goes back to page 1."""
        target = replace(self, **{"page": 1, **changes}) if changes else self
        pairs: list[tuple[str, str]] = []
        if target.q:
            pairs.append(("q", target.q))
        if target.cat:
            pairs.append(("cat", target.cat))
        pairs += [("tienda", s) for s in target.stores]
        pairs += [("talle", s) for s in target.sizes]
        if target.min_price:
            pairs.append(("min", str(target.min_price)))
        if target.max_price:
            pairs.append(("max", str(target.max_price)))
        if target.in_stock:
            pairs.append(("stock", "1"))
        if target.on_sale:
            pairs.append(("oferta", "1"))
        if target.sort != "nuevo":
            pairs.append(("orden", target.sort))
        if target.page > 1:
            pairs.append(("pagina", str(target.page)))
        return urlencode(pairs)

    def without(self, field: str, value: str) -> "Filters":
        """A copy with one store or size removed."""
        return replace(self, **{field: tuple(v for v in getattr(self, field) if v != value), "page": 1})


def format_price(price: Decimal | None) -> str:
    """Uruguayan style: $ 1.668, with decimals only when there are cents."""
    if price is None:
        return "Consultar"
    whole, cents = divmod(int((price * 100).to_integral_value()), 100)
    text = f"{whole:,}".replace(",", ".")
    return f"$ {text},{cents:02d}" if cents else f"$ {text}"


def thumb(url: str, width: int) -> str:
    """Asks Shopify's image CDN for a smaller picture. Other hosts are left alone."""
    if "cdn.shopify.com" not in url:
        return url
    return f"{url}{'&' if '?' in url else '?'}width={width}"


def size_sort_key(size: str) -> tuple:
    upper = size.upper()
    if upper in SIZE_ORDER:
        return (0, SIZE_ORDER.index(upper), "")
    if re.fullmatch(r"\d+([.,]\d+)?", size):
        return (1, float(size.replace(",", ".")), "")
    return (2, 0, upper)


# --- queries -------------------------------------------------------------------

# Stores publish the pre-discount price per variant ("compare_at_price" on Shopify).
# PRODUCTS is the products table plus that price as compare_at (NULL when there is none).
PRODUCTS = r"""(
    SELECT *, CASE WHEN jsonb_typeof(raw->'variants') = 'array' THEN (
        SELECT max((v->>'compare_at_price')::numeric)
        FROM jsonb_array_elements(raw->'variants') AS v
        WHERE v->>'compare_at_price' ~ '^[0-9]+(\.[0-9]+)?$'
    ) END AS compare_at
    FROM products
) AS products"""
ON_SALE = "compare_at > price"
SALE_COLUMNS = (
    f"CASE WHEN {ON_SALE} THEN compare_at END AS was_price, "
    f"CASE WHEN {ON_SALE} THEN round(100 * (1 - price / compare_at))::int END AS discount"
)
CARD_COLUMNS = (
    "id, store_slug, title, price, currency, sizes, in_stock, image_urls[1] AS image, "
    f"first_seen_at > now() - interval '7 days' AS is_new, {SALE_COLUMNS}"
)


def _where(f: Filters) -> tuple[str, list]:
    clauses, params = ["removed_at IS NULL"], []
    for word in f.q.split()[:MAX_QUERY_WORDS]:
        like = "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        clauses.append("(title ILIKE %s OR vendor ILIKE %s)")
        params += [like, like]
    if f.cat:
        clauses.append("title ~* %s")
        params.append(CATEGORIES[f.cat].pattern)
    if f.stores:
        clauses.append("store_slug = ANY(%s)")
        params.append(list(f.stores))
    if f.sizes:
        clauses.append("sizes && %s::text[]")
        params.append(list(f.sizes))
    if f.min_price:
        clauses.append("price >= %s")
        params.append(f.min_price)
    if f.max_price:
        clauses.append("price <= %s")
        params.append(f.max_price)
    if f.in_stock:
        clauses.append("in_stock")
    if f.on_sale:
        clauses.append(ON_SALE)
    return " AND ".join(clauses), params


@dataclass
class Page:
    items: list[dict]
    total: int
    page: int
    pages: int


def search(conn: psycopg.Connection, f: Filters) -> Page:
    where, params = _where(f)
    total = conn.execute(f"SELECT count(*) AS n FROM {PRODUCTS} WHERE {where}", params).fetchone()["n"]
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(f.page, pages)
    items = conn.execute(
        f"SELECT {CARD_COLUMNS} FROM {PRODUCTS} WHERE {where} "
        f"ORDER BY {SORTS[f.sort][1]} LIMIT %s OFFSET %s",
        [*params, PAGE_SIZE, (page - 1) * PAGE_SIZE],
    ).fetchall()
    return Page(items=items, total=total, page=page, pages=pages)


def get_product(conn: psycopg.Connection, product_id: int) -> dict | None:
    return conn.execute(
        "SELECT id, store_slug, title, url, price, currency, sizes, in_stock, image_urls, vendor, "
        f"last_seen_at, removed_at IS NOT NULL AS removed, {SALE_COLUMNS} FROM {PRODUCTS} WHERE id = %s",
        (product_id,),
    ).fetchone()


def related(conn: psycopg.Connection, product: dict, limit: int = 8) -> list[dict]:
    return conn.execute(
        f"SELECT {CARD_COLUMNS} FROM {PRODUCTS} "
        "WHERE removed_at IS NULL AND store_slug = %s AND id <> %s "
        "ORDER BY in_stock DESC, first_seen_at DESC, id DESC LIMIT %s",
        (product["store_slug"], product["id"], limit),
    ).fetchall()


def store_stats(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        "SELECT store_slug AS slug, count(*) AS total, count(*) FILTER (WHERE in_stock) AS in_stock, "
        "max(last_seen_at) AS updated_at FROM products WHERE removed_at IS NULL "
        "GROUP BY store_slug ORDER BY count(*) DESC, store_slug"
    ).fetchall()


def size_options(conn: psycopg.Connection, limit: int = 24) -> list[str]:
    rows = conn.execute(
        "SELECT size FROM products, unnest(sizes) AS size WHERE removed_at IS NULL "
        "GROUP BY size ORDER BY count(*) DESC LIMIT %s",
        (limit,),
    ).fetchall()
    return sorted((r["size"] for r in rows), key=size_sort_key)
