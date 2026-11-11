"""Loads and validates stores.yaml and the environment variables."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from scraper.models import StoreConfig

AUDIENCES = ("men", "unisex", "mixed")
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DEFAULT_CONTACT_URL = "https://github.com/GonzaloVarelaKuolas/ropa-uy"


class ConfigError(Exception):
    """stores.yaml or an environment variable is invalid."""


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    stores_file: str
    contact_url: str
    requests_per_second: float


def load_stores(path: str | Path, known_platforms: Iterable[str]) -> list[StoreConfig]:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"stores file not found: {path}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"stores file is not valid YAML: {path}: {exc}") from None

    entries = (data or {}).get("stores") if isinstance(data, dict) else None
    if not entries:
        raise ConfigError(f"no stores listed in {path}")

    platforms = set(known_platforms)
    stores: list[StoreConfig] = []
    seen: set[str] = set()
    for entry in entries:
        store = _parse_store(entry, platforms)
        if store.slug in seen:
            raise ConfigError(f"duplicate store slug: {store.slug}")
        seen.add(store.slug)
        stores.append(store)
    return stores


def _parse_store(entry: object, platforms: set[str]) -> StoreConfig:
    if not isinstance(entry, dict):
        raise ConfigError(f"each store must be a mapping, got: {entry!r}")
    missing = [key for key in ("slug", "name", "url", "platform") if not entry.get(key)]
    if missing:
        raise ConfigError(f"store {entry.get('slug', '?')} is missing: {', '.join(missing)}")

    slug = str(entry["slug"])
    if not SLUG_PATTERN.match(slug):
        raise ConfigError(f"store slug must be lowercase letters, digits or '-': {slug}")

    url = str(entry["url"]).rstrip("/")
    if not url.startswith("https://"):
        raise ConfigError(f"store {slug} url must use https://, got: {url}")

    platform = str(entry["platform"])
    if platform not in platforms:
        raise ConfigError(f"store {slug} has unknown platform: {platform}")

    audience = str(entry.get("audience") or "unisex")
    if audience not in AUDIENCES:
        raise ConfigError(f"store {slug} audience must be one of {AUDIENCES}, got: {audience}")

    collections = tuple(str(c) for c in (entry.get("collections") or ()))
    if audience == "mixed" and not collections:
        raise ConfigError(f"store {slug} is 'mixed' so it needs collections to scrape")

    return StoreConfig(
        slug=slug,
        name=str(entry["name"]),
        url=url,
        platform=platform,
        currency=str(entry.get("currency") or "UYU"),
        audience=audience,
        collections=collections,
    )


def load_settings(env: Mapping[str, str], dry_run: bool) -> Settings:
    database_url = env.get("DATABASE_URL") or None
    if database_url is None and not dry_run:
        raise ConfigError("DATABASE_URL is required (or use --dry-run)")

    raw_rate = env.get("REQUESTS_PER_SECOND", "1")
    try:
        rate = float(raw_rate)
    except ValueError:
        raise ConfigError(f"REQUESTS_PER_SECOND must be a number, got: {raw_rate}") from None
    if rate <= 0:
        raise ConfigError(f"REQUESTS_PER_SECOND must be above 0, got: {raw_rate}")

    return Settings(
        database_url=database_url,
        stores_file=env.get("STORES_FILE") or "stores.yaml",
        contact_url=env.get("CONTACT_URL") or DEFAULT_CONTACT_URL,
        requests_per_second=rate,
    )
