import psycopg


def test_home_lists_products(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "Buzo Retro" in page.text
    assert "$ 1.668" in page.text
    assert "6 prendas" in page.text
    assert "Campera Vieja" not in page.text
    assert "width=600" in page.text
    assert 'lang="es"' in page.text


def test_home_filters_from_the_url(client):
    page = client.get("/?q=remera&tienda=ramon")
    assert "Remera Anime" in page.text
    assert "Remera Oversize Negra" not in page.text
    assert "1 prenda" in page.text


def test_home_shows_store_names_from_stores_file(client):
    page = client.get("/")
    assert "Kaboa" in page.text
    assert "Ramon" in page.text  # not in stores.yaml: falls back to the slug


def test_empty_results_message(client):
    page = client.get("/?q=zzzzzz")
    assert page.status_code == 200
    assert "No encontramos prendas" in page.text


def test_search_text_is_escaped(client):
    page = client.get("/?q=<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in page.text


def test_product_page(client):
    page = client.get("/p/1")
    assert page.status_code == 200
    assert "Buzo Retro" in page.text
    assert "Ver en Kaboa" in page.text
    assert "https://kaboa.uy/products/1?utm_source=ropa-uy" in page.text
    assert "Buzo Industrial" in page.text  # more from the store


def test_removed_product_says_so(client):
    page = client.get("/p/5")
    assert page.status_code == 200
    assert "Ya no está disponible" in page.text


def test_unknown_product_and_page_are_404(client):
    assert client.get("/p/999").status_code == 404
    assert client.get("/p/abc").status_code == 404
    missing = client.get("/nada")
    assert missing.status_code == 404
    assert "No encontramos esa página" in missing.text


def test_stores_page(client):
    page = client.get("/tiendas")
    assert page.status_code == 200
    assert "Kaboa" in page.text and "4 prendas" in page.text
    assert "https://www.kaboa.com.uy" in page.text


def test_health_endpoints(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").status_code == 200


def test_static_files_are_served(client):
    assert client.get("/static/style.css").status_code == 200


def test_works_before_the_scraper_has_ever_run(conn, client):
    conn.execute("DROP TABLE products, scrape_runs CASCADE")
    conn.commit()
    page = client.get("/")
    assert page.status_code == 200
    assert "Todavía no hay prendas" in page.text
    assert client.get("/tiendas").status_code == 200
    assert client.get("/p/1").status_code == 404


def test_database_down_shows_a_friendly_503(tmp_path):
    from fastapi.testclient import TestClient

    from web.app import create_app

    client = TestClient(create_app("postgresql://nobody@127.0.0.1:1/nope?connect_timeout=1", None))
    page = client.get("/")
    assert page.status_code == 503
    assert "Volvé a intentar" in page.text
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 503


def test_sale_shows_old_price_and_discount(conn, client):
    conn.execute(
        "UPDATE products SET raw = '{\"variants\": [{\"compare_at_price\": \"3336.00\"}]}' WHERE title = 'Buzo Retro'"
    )
    conn.commit()
    html = client.get("/?oferta=1").text
    assert "Buzo Retro" in html and "Remera Anime" not in html
    assert "$ 3.336" in html and "-50%" in html
    assert 'name="oferta" value="1" checked' in html
