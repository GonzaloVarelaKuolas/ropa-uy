import pytest

from scraper.config import ConfigError, load_settings, load_stores
from scraper.models import StoreConfig

PLATFORMS = ["shopify"]

KABOA = """
stores:
  - slug: kaboa
    name: Kaboa
    url: https://www.kaboa.com.uy/
    platform: shopify
"""


def write(tmp_path, text):
    path = tmp_path / "stores.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def store_yaml(**overrides):
    fields = {
        "slug": "kaboa",
        "name": "Kaboa",
        "url": "https://www.kaboa.com.uy",
        "platform": "shopify",
    }
    fields.update(overrides)
    return "stores:\n" + store_item(fields)


def store_item(fields):
    lines = [f"{key}: {value}" for key, value in fields.items()]
    return "  - " + "\n    ".join(lines) + "\n"


def test_loads_valid_store(tmp_path):
    stores = load_stores(write(tmp_path, KABOA), PLATFORMS)
    assert stores == [
        StoreConfig(
            slug="kaboa",
            name="Kaboa",
            url="https://www.kaboa.com.uy",
            platform="shopify",
            currency="UYU",
            audience="unisex",
            collections=(),
        )
    ]


def test_rejects_duplicate_slug(tmp_path):
    text = store_yaml() + store_item(
        {"slug": "kaboa", "name": "Other", "url": "https://other.uy", "platform": "shopify"}
    )
    with pytest.raises(ConfigError, match="kaboa"):
        load_stores(write(tmp_path, text), PLATFORMS)


def test_rejects_uppercase_slug(tmp_path):
    with pytest.raises(ConfigError, match="Kaboa"):
        load_stores(write(tmp_path, store_yaml(slug="Kaboa")), PLATFORMS)


def test_rejects_unknown_platform(tmp_path):
    with pytest.raises(ConfigError, match="wix"):
        load_stores(write(tmp_path, store_yaml(platform="wix")), PLATFORMS)


def test_rejects_http_url(tmp_path):
    with pytest.raises(ConfigError, match="http://"):
        load_stores(write(tmp_path, store_yaml(url="http://kaboa.com.uy")), PLATFORMS)


def test_mixed_requires_collections(tmp_path):
    with pytest.raises(ConfigError, match="collections"):
        load_stores(write(tmp_path, store_yaml(audience="mixed")), PLATFORMS)


def test_mixed_with_collections_is_valid(tmp_path):
    stores = load_stores(
        write(tmp_path, store_yaml(audience="mixed", collections="[hombre]")), PLATFORMS
    )
    assert stores[0].collections == ("hombre",)


def test_rejects_bad_audience(tmp_path):
    with pytest.raises(ConfigError, match="kids"):
        load_stores(write(tmp_path, store_yaml(audience="kids")), PLATFORMS)


def test_rejects_empty_store_list(tmp_path):
    with pytest.raises(ConfigError):
        load_stores(write(tmp_path, "stores: []\n"), PLATFORMS)


def test_missing_file_is_config_error(tmp_path):
    with pytest.raises(ConfigError, match="stores.yaml"):
        load_stores(tmp_path / "stores.yaml", PLATFORMS)


def test_settings_requires_database_url_unless_dry_run():
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        load_settings({}, dry_run=False)
    settings = load_settings({}, dry_run=True)
    assert settings.database_url is None
    assert settings.stores_file == "stores.yaml"
    assert settings.requests_per_second == 1.0
    assert settings.contact_url == "https://github.com/GonzaloVarelaKuolas/ropa-uy"


def test_settings_reads_env():
    settings = load_settings(
        {
            "DATABASE_URL": "postgresql://x",
            "STORES_FILE": "/config/stores.yaml",
            "CONTACT_URL": "https://example.com",
            "REQUESTS_PER_SECOND": "2.5",
        },
        dry_run=False,
    )
    assert settings.database_url == "postgresql://x"
    assert settings.stores_file == "/config/stores.yaml"
    assert settings.contact_url == "https://example.com"
    assert settings.requests_per_second == 2.5


def test_settings_rejects_non_positive_rate():
    with pytest.raises(ConfigError, match="REQUESTS_PER_SECOND"):
        load_settings({"REQUESTS_PER_SECOND": "0"}, dry_run=True)
    with pytest.raises(ConfigError, match="REQUESTS_PER_SECOND"):
        load_settings({"REQUESTS_PER_SECOND": "fast"}, dry_run=True)
