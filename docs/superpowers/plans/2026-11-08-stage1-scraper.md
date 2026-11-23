# Stage 1 Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python scraper that reads Shopify store catalogs into PostgreSQL, running as a CronJob on a local k3d cluster.

**Architecture:** Small focused modules: config loading, a polite HTTP client, one reader per platform (Shopify only), a database layer, and a run loop that sends each store's products to a "sink" (PostgreSQL, or stdout for `--dry-run`). Packaged as one Docker image and deployed with plain YAML manifests next to a single-instance PostgreSQL StatefulSet.

**Tech Stack:** Python 3.12+, httpx, PyYAML, psycopg 3, pytest; Docker; k3d (k3s); PostgreSQL 16.

**Spec:** `docs/superpowers/specs/2026-11-07-scraper-design.md`

## Global Constraints

- Python `>=3.12`; Docker base image `python:3.12-slim`.
- Runtime dependencies only: `httpx>=0.27,<1`, `PyYAML>=6,<7`, `psycopg[binary]>=3.2,<4`. Dev: `pytest>=8`.
- User agent: `ropa-uy-bot/0.1 (+{CONTACT_URL})`. `CONTACT_URL` defaults to `https://github.com/GonzaloVarelaKuolas/ropa-uy`.
- HTTP: 20 s timeout, `REQUESTS_PER_SECOND` default `1` per host, 3 attempts, backoff `2 * 2**(attempt-1)` seconds (2, 4) on network errors, 429 and 5xx.
- Shopify: `limit=250`, at most 100 pages per listing, size option regex `talle|talla|size|tamaño` (case-insensitive).
- Env vars: `DATABASE_URL` (required unless `--dry-run`), `STORES_FILE` (default `stores.yaml`), `CONTACT_URL`, `REQUESTS_PER_SECOND`.
- Exit codes: `0` all stores ok, `1` any store failed, `2` config or usage error.
- Logs: one line per event on stdout, `event=<name> key=value ...`.
- Kubernetes: namespace `ropa-uy`; CronJob `0 */6 * * *`, `concurrencyPolicy: Forbid`, `backoffLimit: 1`, `ttlSecondsAfterFinished: 86400`; non-root (UID `10001`); Postgres PVC `1Gi`, storage class `local-path`.
- No real network calls in tests. Database tests are skipped unless `TEST_DATABASE_URL` is set.
- All commands below run from `services/scraper/` unless they say otherwise.

## Review Focus

1. The same product listed in two configured collections must be stored once, not twice (Task 3: `test_dedupes_products_across_collections`).
2. Shopify returns `tags` as a list on some stores and as a comma-separated string on others; both must become a list (Task 3: `test_tags_string_and_list`).
3. A product with no variants or unparseable prices must not crash the store's run: `price=None`, `in_stock=False` (Task 3: `test_product_without_variants`).
4. A store that fails after other stores succeeded must leave the earlier stores' data saved and its own products untouched (not marked removed), with exit code 1 (Task 4: `test_failed_run_marks_nothing`; Task 5: `test_failing_store_does_not_stop_others`).
5. `--store` with a slug that isn't in `stores.yaml` must exit 2 with a clear message and make no requests (Task 5: `test_unknown_store_slug`).
6. A store that suddenly returns an empty catalog (maintenance page, robots.txt change) must not mark all its products removed (Task 5: `test_zero_products_counts_as_failure`).

---

### Task 1: Project scaffold, models and config

**Files:**
- Create: `services/scraper/requirements.txt`, `services/scraper/requirements-dev.txt`, `services/scraper/pyproject.toml` (only `[tool.pytest.ini_options]`: `pythonpath = ["."]`, `testpaths = ["tests"]`)
- Create: `services/scraper/scraper/__init__.py` (empty), `services/scraper/scraper/models.py`, `services/scraper/scraper/config.py`
- Create: `services/scraper/stores.yaml` (the Kaboa entry from the spec)
- Test: `services/scraper/tests/test_config.py`

**Interfaces:**
- Produces:
  - `models.StoreConfig` (frozen dataclass): `slug: str, name: str, url: str, platform: str, currency: str = "UYU", audience: str = "unisex", collections: tuple[str, ...] = ()`
  - `models.Product` (dataclass): `store_slug: str, external_id: str, title: str, url: str, price: Decimal | None, currency: str, sizes: list[str], in_stock: bool, image_urls: list[str], vendor: str | None, product_type: str | None, tags: list[str], raw: dict`
  - `config.ConfigError(Exception)`
  - `config.load_stores(path: str | Path, known_platforms: Iterable[str]) -> list[StoreConfig]` (strips a trailing `/` from `url`)
  - `config.Settings` (frozen dataclass): `database_url: str | None, stores_file: str, contact_url: str, requests_per_second: float`
  - `config.load_settings(env: Mapping[str, str], dry_run: bool) -> Settings`

- [ ] **Step 1: Write the failing tests** in `tests/test_config.py`, each writing a YAML string to `tmp_path`:
  - `test_loads_valid_store`: the Kaboa entry gives `StoreConfig(slug="kaboa", ..., currency="UYU", audience="unisex", collections=())`
  - `test_rejects_duplicate_slug`, `test_rejects_uppercase_slug`, `test_rejects_unknown_platform`, `test_rejects_http_url`, `test_mixed_requires_collections`, `test_rejects_bad_audience`: each `pytest.raises(ConfigError)` with the offending slug or value in the message
  - `test_settings_requires_database_url_unless_dry_run`: `load_settings({}, dry_run=False)` raises `ConfigError`; `load_settings({}, dry_run=True)` returns `database_url=None, stores_file="stores.yaml", requests_per_second=1.0`
  - `test_settings_rejects_non_positive_rate`: `REQUESTS_PER_SECOND="0"` raises `ConfigError`

- [ ] **Step 2: Run them to verify they fail**
  Run: `python -m pip install -r requirements-dev.txt && python -m pytest tests/test_config.py -v`
  Expected: FAIL with `ModuleNotFoundError: No module named 'scraper.config'`

- [ ] **Step 3: Implement `models.py` and `config.py`** with the interfaces above. Use `yaml.safe_load`; a missing or empty `stores` list is a `ConfigError`.

- [ ] **Step 4: Run tests to verify they pass**
  Run: `python -m pytest tests/test_config.py -v`
  Expected: all PASS

- [ ] **Step 5: Commit**
  `git add services/scraper && git commit -m "feat(scraper): store config and models"`

### Task 2: Polite HTTP client

**Files:**
- Create: `services/scraper/scraper/http.py`
- Test: `services/scraper/tests/test_http.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `http.FetchError(Exception)`: request failed after retries, or a non-retryable status
  - `http.RobotsDisallowed(FetchError)`: the URL is blocked by robots.txt
  - `http.PoliteClient(contact_url: str, requests_per_second: float = 1.0, *, transport: httpx.BaseTransport | None = None, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep, max_attempts: int = 3, backoff_base: float = 2.0, timeout: float = 20.0)`
  - `PoliteClient.get_json(url: str) -> Any`
  - `PoliteClient.close() -> None`

- [ ] **Step 1: Write the failing tests** using `httpx.MockTransport`, a fake clock and a `sleeps: list[float]` recorder passed as `sleep`:
  - `test_sends_user_agent`: the request header `User-Agent` equals `ropa-uy-bot/0.1 (+https://example.com)`
  - `test_retries_429_then_succeeds`: responses 429, 200 return the JSON; `sleeps` contains `2.0`
  - `test_retries_5xx_and_gives_up`: three 503s raise `FetchError`; backoff sleeps `[2.0, 4.0]` appear in `sleeps`
  - `test_404_is_not_retried`: one 404 raises `FetchError` after exactly one request to that URL
  - `test_robots_disallow`: robots.txt `User-agent: *\nDisallow: /products` makes `get_json(".../products.json")` raise `RobotsDisallowed` with no request made to that URL
  - `test_robots_404_allows_all` and `test_robots_500_raises_fetch_error`
  - `test_robots_fetched_once_per_host`: two `get_json` calls on one host make one robots.txt request
  - `test_rate_limit_waits_between_requests`: at 1 request/second with a frozen clock, the second request sleeps `1.0` first

- [ ] **Step 2: Run them to verify they fail**
  Run: `python -m pytest tests/test_http.py -v`
  Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `PoliteClient`** with an `httpx.Client` (its `transport` and `timeout`), `urllib.robotparser.RobotFileParser.parse()` on the fetched text, robots cached per `scheme://host`, and a per-host last-request time that `sleep`s the remaining `1 / requests_per_second`. Robots requests go through the same rate limit.

- [ ] **Step 4: Run tests to verify they pass**
  Run: `python -m pytest tests/test_http.py -v`
  Expected: all PASS

- [ ] **Step 5: Commit**
  `git add services/scraper && git commit -m "feat(scraper): polite HTTP client"`

### Task 3: Shopify reader

**Files:**
- Create: `services/scraper/scraper/platforms/__init__.py`, `services/scraper/scraper/platforms/shopify.py`
- Create: `services/scraper/tests/fixtures/shopify_products.json` (2 products: one with a `Talle` option and mixed availability, one with a `Color` option only)
- Test: `services/scraper/tests/test_shopify.py`

**Interfaces:**
- Consumes: `StoreConfig`, `Product` (Task 1); `PoliteClient.get_json` (Task 2).
- Produces:
  - `platforms.Reader = Callable[[StoreConfig, PoliteClient], Iterator[Product]]`
  - `platforms.READERS: dict[str, Reader] = {"shopify": shopify.fetch_products}`
  - `shopify.fetch_products(store: StoreConfig, client: PoliteClient) -> Iterator[Product]`
  - `shopify.parse_product(store: StoreConfig, raw: dict) -> Product`

Rules: product `url` = `{store.url}/products/{handle}`; `external_id` = `str(raw["id"])`; `image_urls` = each `images[].src`; listing URL = `{store.url}/products.json?limit=250&page={n}` with no collections, else `{store.url}/collections/{handle}/products.json?limit=250&page={n}` for each collection; stop at the first page whose `products` is empty, or after page 100. A `RobotsDisallowed` from the client is not caught here: the store fails for that run (logged by Task 5), which is how the spec's "skipped and logged" is met without a zero-product run marking the whole catalog removed.

- [ ] **Step 1: Write the failing tests** (a fake client: a small class with `get_json(url)` that returns from a `dict[url, payload]` and records the URLs requested):
  - `test_parse_price_sizes_stock`: variants priced `"1590.00"` (available, `M`), `"1290.00"` (unavailable, `S`), `"1490.00"` (available, `L`) give `price=Decimal("1490.00")`, `sizes=["M", "L"]` in option-value order, `in_stock=True`
  - `test_price_falls_back_to_lowest_when_none_available`: no variant available gives the lowest price overall and `in_stock=False`
  - `test_size_option_name_match`: options named `Talle`, `TALLA`, `Size` and `Tamaño` are each detected; `Color` gives `sizes=[]`
  - `test_product_without_variants`: `variants=[]` gives `price=None, in_stock=False, sizes=[]`
  - `test_tags_string_and_list`: `"oversize, negro"` and `["oversize", "negro"]` both give `["oversize", "negro"]`
  - `test_paginates_until_empty_page`: pages 1–2 have products and page 3 is empty; it yields all products and requests page 3 last
  - `test_stops_after_100_pages`: a client that always returns one product makes exactly 100 listing requests
  - `test_uses_collection_urls_for_mixed_store`: `collections=("hombre",)` requests only `/collections/hombre/products.json?...`
  - `test_dedupes_products_across_collections`: the same `id` in two collections is yielded once
  - `test_reader_registered`: `READERS["shopify"] is shopify.fetch_products`

- [ ] **Step 2: Run them to verify they fail**
  Run: `python -m pytest tests/test_shopify.py -v`
  Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `parse_product` and `fetch_products`** following the rules above. Parse prices with `Decimal`, skipping a variant whose price doesn't parse. A variant's size is `variant[f"option{i+1}"]`, where `i` is the index of the size option in `raw["options"]`.

- [ ] **Step 4: Run tests to verify they pass**
  Run: `python -m pytest tests/test_shopify.py -v`
  Expected: all PASS

- [ ] **Step 5: Commit**
  `git add services/scraper && git commit -m "feat(scraper): Shopify reader"`

### Task 4: Database layer

**Files:**
- Create: `services/scraper/scraper/schema.sql`, `services/scraper/scraper/db.py`
- Test: `services/scraper/tests/test_db.py` (module-level `pytest.mark.skipif` when `TEST_DATABASE_URL` is unset; a fixture applies the schema and truncates both tables before each test)

**Interfaces:**
- Consumes: `Product` (Task 1).
- Produces:
  - `db.connect(database_url: str) -> psycopg.Connection`
  - `db.apply_schema(conn: psycopg.Connection) -> None` (runs `schema.sql`, loaded from `Path(__file__).with_name("schema.sql")`)
  - `db.start_run(conn, store_slug: str) -> tuple[int, datetime]` (inserts a `running` row and returns its id and `started_at`)
  - `db.upsert_products(conn, products: Iterable[Product], seen_at: datetime) -> int` (returns the count written)
  - `db.mark_removed(conn, store_slug: str, run_started_at: datetime) -> int`
  - `db.finish_run(conn, run_id: int, status: str, products_seen: int, error: str | None) -> None`
  - None of these commit; the caller controls transactions.

Schema: `products` has the spec's columns plus `id bigserial primary key`, `first_seen_at`, `last_seen_at` and `removed_at` (`timestamptz`), and `UNIQUE (store_slug, external_id)`. `raw` is `jsonb`, written with `psycopg.types.json.Jsonb`. `scrape_runs` has `status text CHECK (status IN ('running','ok','failed'))`.

- [ ] **Step 1: Write the failing tests**:
  - `test_apply_schema_twice`: a second `apply_schema` call raises nothing
  - `test_upsert_inserts_then_updates`: two upserts of the same product with a changed price leave 1 row with the new price, and `first_seen_at` unchanged
  - `test_mark_removed_only_unseen`: products A and B seen at t0, only A seen at t1, then `mark_removed(slug, t1)` marks B only (returns 1)
  - `test_product_returns_after_removal`: an upsert after removal sets `removed_at` back to NULL
  - `test_failed_run_marks_nothing`: a run that ends with `finish_run(..., "failed", ...)` and no `mark_removed` call leaves `removed_at` NULL for all products, and `scrape_runs.status = 'failed'`
  - `test_mark_removed_scoped_to_store`: another store's products are untouched

- [ ] **Step 2: Run them to verify they fail**
  Start a throwaway database (from the repo root, with Docker):
  `docker run -d --name ropa-test-pg -e POSTGRES_PASSWORD=test -p 5433:5432 postgres:16-alpine`
  Run: `TEST_DATABASE_URL=postgresql://postgres:test@localhost:5433/postgres python -m pytest tests/test_db.py -v`
  Expected: FAIL with `ModuleNotFoundError`. (Without the variable, the tests show as SKIPPED.)

- [ ] **Step 3: Implement `schema.sql` and `db.py`.** The upsert is `INSERT ... ON CONFLICT (store_slug, external_id) DO UPDATE SET ... last_seen_at = EXCLUDED.last_seen_at, removed_at = NULL`.

- [ ] **Step 4: Run tests to verify they pass** (same command as Step 2)
  Expected: all PASS

- [ ] **Step 5: Commit**
  `git add services/scraper && git commit -m "feat(scraper): PostgreSQL storage"`

### Task 5: Run loop, sinks and CLI

**Files:**
- Create: `services/scraper/scraper/run.py`, `services/scraper/scraper/__main__.py`
- Test: `services/scraper/tests/test_run.py`

**Interfaces:**
- Consumes: `load_stores`, `load_settings`, `ConfigError` (Task 1); `PoliteClient`, `FetchError` (Task 2); `READERS`, `Reader` (Task 3); `db.*` (Task 4).
- Produces:
  - `run.log(event: str, **fields) -> None`: prints `event=<event> k=v ...` to stdout, quoting values that contain spaces
  - `run.Sink` (Protocol): `store_started(store: StoreConfig) -> None`, `store_succeeded(store: StoreConfig, products: list[Product]) -> None`, `store_failed(store: StoreConfig, error: str) -> None`
  - `run.PrintSink`: `store_succeeded` prints one JSON object per product (Decimal as string; `raw` left out)
  - `run.DbSink(conn: psycopg.Connection)`: `store_started` calls `start_run` and commits; `store_succeeded` calls `upsert_products`, `mark_removed` and `finish_run("ok")` in one transaction, then commits; `store_failed` rolls back, calls `finish_run("failed", error=...)`, and commits
  - `run.StoreResult` (dataclass): `slug: str, ok: bool, products_seen: int, error: str | None`
  - `run.run_stores(stores: list[StoreConfig], client: PoliteClient, readers: Mapping[str, Reader], sink: Sink) -> list[StoreResult]`
  - `__main__.main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int`

Behaviour: stores run one at a time. A store whose reader returns zero products counts as failed with error `no products returned` (an empty response must never mark a whole catalog removed). Any exception from a reader or the sink's `store_succeeded` is caught; the run logs `event=store_failed slug=... error=...`, calls `store_failed`, and continues. `main` parses `run [--store SLUG] [--dry-run]`, loads settings and stores (a `ConfigError` logs and returns 2), filters by `--store`, builds the client and sink, applies the schema (database mode), runs, and returns 0 or 1.

- [ ] **Step 1: Write the failing tests** (a fake reader dict and a recording sink; no network, no database):
  - `test_all_stores_ok`: two stores give two `ok` results, the sink sees started/succeeded for each, in order
  - `test_failing_store_does_not_stop_others`: the first store's reader raises `FetchError("boom")`; the second still succeeds; results are `[False, True]`; the sink saw `store_failed(first, "boom")`
  - `test_zero_products_counts_as_failure`: a reader that yields nothing gives `ok=False, error="no products returned"`, and the sink saw `store_failed`, not `store_succeeded`
  - `test_main_dry_run_prints_json`: with `env={"STORES_FILE": <tmp yaml>}`, `--dry-run`, and `READERS` monkeypatched to a fake, `main(["run", "--dry-run"], env)` returns 0, and captured stdout has one JSON line per product with `"price": "1490.00"`
  - `test_main_returns_1_when_a_store_fails`
  - `test_unknown_store_slug`: `main(["run", "--dry-run", "--store", "nope"], env)` returns 2, prints `event=config_error` naming `nope`, and the fake reader is never called
  - `test_main_requires_database_url`: `main(["run"], {"STORES_FILE": ...})` returns 2

- [ ] **Step 2: Run them to verify they fail**
  Run: `python -m pytest tests/test_run.py -v`
  Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `run.py` and `__main__.py`** with the interfaces above. `main` looks up `READERS` at call time (`platforms.READERS`), so the test monkeypatch works.

- [ ] **Step 4: Run the whole suite**
  Run: `python -m pytest -v`
  Expected: all PASS (database tests SKIPPED without `TEST_DATABASE_URL`)

- [ ] **Step 5: Try a real dry run against Kaboa** (the one manual network check)
  Run: `python -m scraper run --dry-run --store kaboa`
  Expected: JSON lines of Kaboa products, then `event=run_finished ok=1 failed=0`. If the network blocks it, note that and continue.

- [ ] **Step 6: Commit**
  `git add services/scraper && git commit -m "feat(scraper): run loop and CLI"`

### Task 6: Docker image and Kubernetes manifests

**Files:**
- Create: `services/scraper/Dockerfile`, `services/scraper/.dockerignore` (`tests/`, `__pycache__/`, `.pytest_cache/`)
- Create: `deploy/k3s/namespace.yaml`, `deploy/k3s/postgres.yaml` (headless Service + StatefulSet), `deploy/k3s/scraper-cronjob.yaml`
- Modify: `README.md` ("Getting started": replace the 🚧 note with the steps in Step 4 below; tick "Shopify scraper" and "k3s manifests" in Current progress)

**Interfaces:**
- Consumes: `python -m scraper run` (Task 5).
- Produces (names that the manifests and README share):
  - Image `ropa-uy-scraper:0.1.0`
  - Secret `ropa-uy-db` with keys `postgres-password` and `database-url`
  - ConfigMap `scraper-stores` with key `stores.yaml`, mounted at `/config/stores.yaml`
  - Service `postgres` (port 5432), StatefulSet `postgres` (image `postgres:16-alpine`, `PGDATA=/var/lib/postgresql/data/pgdata`), CronJob `scraper`

Dockerfile: `python:3.12-slim`; `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`; `COPY requirements.txt` and `pip install --no-cache-dir -r requirements.txt` **before** `COPY scraper/ scraper/`; `useradd --uid 10001 --create-home appuser`; `USER 10001`; `CMD ["python", "-m", "scraper", "run"]`.

CronJob pod: `securityContext.runAsNonRoot: true`, `runAsUser: 10001`; `imagePullPolicy: IfNotPresent`; env `STORES_FILE=/config/stores.yaml` and `DATABASE_URL` from `ropa-uy-db`/`database-url`; resources requests `50m`/`64Mi`, limits `500m`/`256Mi`; `restartPolicy: Never`.

- [ ] **Step 1: Build the image and smoke-test it**
  Run: `docker build -t ropa-uy-scraper:0.1.0 . && docker run --rm ropa-uy-scraper:0.1.0 python -m scraper run --dry-run --store nope`
  Expected: the build succeeds; the run prints `event=config_error` about the missing `stores.yaml` (the image doesn't bundle it; Kubernetes mounts it) and exits 2. That proves the code starts inside the image.
  Also run: `docker run --rm ropa-uy-scraper:0.1.0 id -u`. Expected: `10001`.

- [ ] **Step 2: Validate the manifests** (from the repo root)
  Run: `kubeconform -strict -summary deploy/k3s/`
  Expected: `Summary: 4 resources found in 3 files - Valid: 4, Invalid: 0` (install kubeconform from its GitHub release if it's missing)

- [ ] **Step 3: Write the README "Getting started"** with these commands, in order, each with one line on what it teaches:
  1. `k3d cluster create ropa-uy`
  2. `kubectl apply -f deploy/k3s/namespace.yaml`
  3. `kubectl -n ropa-uy create secret generic ropa-uy-db --from-literal=postgres-password=<choose one> --from-literal=database-url=postgresql://postgres:<same>@postgres:5432/postgres`
  4. `kubectl -n ropa-uy create configmap scraper-stores --from-file=stores.yaml=services/scraper/stores.yaml`
  5. `docker build -t ropa-uy-scraper:0.1.0 services/scraper && k3d image import ropa-uy-scraper:0.1.0 -c ropa-uy`
  6. `kubectl apply -f deploy/k3s/`
  7. `kubectl -n ropa-uy create job --from=cronjob/scraper scraper-manual-1` then `kubectl -n ropa-uy logs -f job/scraper-manual-1`
  8. `kubectl -n ropa-uy exec -it postgres-0 -- psql -U postgres -c "select store_slug, count(*) from products group by 1;"`

- [ ] **Step 4: Run the full test suite once more**
  Run: `python -m pytest -v` (in `services/scraper/`)
  Expected: all PASS

- [ ] **Step 5: Commit**
  `git add services/scraper deploy README.md && git commit -m "feat: scraper image and k3s manifests"`

### Task 7: First run on the k3d cluster (done by Gonzalo, on his PC)

This is the learning step. It has no code, and it's the acceptance test for stage 1.

- [ ] Start Docker Desktop; install k3d (`winget install k3d`).
- [ ] Follow README "Getting started" steps 1–8.
- [ ] Expected: the manual job's logs end with `event=run_finished ok=1 failed=0`, and the psql query shows a product count for `kaboa`.
- [ ] Then: `kubectl -n ropa-uy get cronjob scraper` shows the 6-hour schedule.
