"""The ropa-uy website: catalog, product page and stores page.

Run locally:  uvicorn web.app:app --reload   (needs DATABASE_URL)
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import yaml
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from psycopg.rows import dict_row
from starlette.exceptions import HTTPException as StarletteHTTPException

from web import catalog
from web.catalog import CATEGORIES, SORTS, Filters

HERE = Path(__file__).parent
REPO_URL = "https://github.com/GonzaloVarelaKuolas/ropa-uy"


class DatabaseUnavailable(Exception):
    pass


def load_store_info(stores_file: str | None) -> dict[str, dict]:
    """Store names and home pages from the scraper's stores.yaml. Optional."""
    if not stores_file:
        return {}
    try:
        data = yaml.safe_load(Path(stores_file).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return {
        str(s["slug"]): {"name": str(s.get("name") or s["slug"]), "url": str(s.get("url") or "")}
        for s in data.get("stores") or []
        if isinstance(s, dict) and s.get("slug")
    }


def outbound(url: str) -> str:
    """The store's product link, tagged so the store can see the visit came from us."""
    parts = urlsplit(url)
    query = f"{parts.query}&utm_source=ropa-uy" if parts.query else "utm_source=ropa-uy"
    return urlunsplit(parts._replace(query=query))


def time_ago(moment: datetime | None) -> str:
    if moment is None:
        return ""
    minutes = int((datetime.now(timezone.utc) - moment).total_seconds() // 60)
    if minutes < 60:
        return "hace menos de una hora"
    if minutes < 60 * 24:
        hours = minutes // 60
        return f"hace {hours} hora{'s' if hours != 1 else ''}"
    days = minutes // (60 * 24)
    return f"hace {days} día{'s' if days != 1 else ''}"


def link(filters: Filters, **changes) -> str:
    """The catalog URL for these filters, optionally with some changed."""
    query = filters.to_query(**changes)
    return f"/?{query}" if query else "/"


def plural(count: int, one: str, many: str) -> str:
    return f"{count:,}".replace(",", ".") + " " + (one if count == 1 else many)


def create_app(database_url: str | None, stores_file: str | None) -> FastAPI:
    app = FastAPI(title="ropa-uy", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    stores = load_store_info(stores_file)

    def store_name(slug: str) -> str:
        return stores.get(slug, {}).get("name") or slug.replace("-", " ").title()

    templates.env.globals.update(
        categories=CATEGORIES, sorts=SORTS, store_name=store_name, repo_url=REPO_URL, link=link,
        static_version=str(int((HERE / "static" / "style.css").stat().st_mtime)),
    )
    templates.env.filters.update(
        price=catalog.format_price, thumb=catalog.thumb, outbound=outbound,
        time_ago=time_ago, plural=plural,
    )

    def get_conn():
        try:
            conn = psycopg.connect(database_url or "", row_factory=dict_row, autocommit=True)
        except psycopg.OperationalError as exc:
            raise DatabaseUnavailable() from exc
        try:
            yield conn
        finally:
            conn.close()

    def render(request: Request, name: str, status_code: int = 200, **context) -> HTMLResponse:
        return templates.TemplateResponse(request, name, context, status_code=status_code)

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, conn=Depends(get_conn)):
        filters = Filters.from_query(request.query_params)
        try:
            page = catalog.search(conn, filters)
            store_stats = catalog.store_stats(conn)
            sizes = catalog.size_options(conn)
        except psycopg.errors.UndefinedTable:  # the scraper has never run
            page, store_stats, sizes = catalog.Page([], 0, 1, 1), [], []
        return render(
            request, "index.html", f=filters, page=page, store_stats=store_stats,
            # keep a size the visitor picked even if it isn't among the common ones
            sizes=sizes + [s for s in filters.sizes if s not in sizes],
            catalog_empty=not store_stats,
        )

    @app.get("/p/{product_id}", response_class=HTMLResponse)
    def product(request: Request, product_id: int, conn=Depends(get_conn)):
        try:
            item = catalog.get_product(conn, product_id) if product_id < 2**62 else None
            more = catalog.related(conn, item) if item else []
        except psycopg.errors.UndefinedTable:
            item, more = None, []
        if item is None:
            raise HTTPException(status_code=404)
        return render(request, "product.html", p=item, more=more)

    @app.get("/tiendas", response_class=HTMLResponse)
    def store_list(request: Request, conn=Depends(get_conn)):
        try:
            stats = catalog.store_stats(conn)
        except psycopg.errors.UndefinedTable:
            stats = []
        for row in stats:
            row["url"] = stores.get(row["slug"], {}).get("url", "")
        return render(request, "stores.html", stats=stats)

    @app.get("/healthz")
    def healthz():
        """Liveness: the process is up. Doesn't touch the database."""
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz(conn=Depends(get_conn)):
        """Readiness: the database answers."""
        conn.execute("SELECT 1")
        return {"status": "ok"}

    @app.exception_handler(DatabaseUnavailable)
    def database_unavailable(request: Request, exc: DatabaseUnavailable):
        if request.url.path == "/readyz":
            return JSONResponse({"status": "database unavailable"}, status_code=503)
        return render(
            request, "message.html", status_code=503, title="Estamos con problemas",
            message="No pudimos cargar el catálogo. Volvé a intentar en unos minutos.",
        )

    @app.exception_handler(StarletteHTTPException)
    def http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return render(
                request, "message.html", status_code=404, title="No encontramos esa página",
                message="Puede que la prenda ya no exista o que el enlace esté mal escrito.",
            )
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    def bad_path(request: Request, exc: RequestValidationError):
        return http_error(request, StarletteHTTPException(status_code=404))

    return app


app = create_app(os.environ.get("DATABASE_URL"), os.environ.get("STORES_FILE"))
