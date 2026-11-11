# Stage 1 scraper: design

Date: 2026-11-07
Status: approved (2026-11-08)

## Why this exists

ropa-uy collects men's clothing from Uruguayan online stores into one place
where people can search and browse by style. The project's main goal is
learning Kubernetes on a real system. The site should cost little enough
that a small income from stores covers it.

This spec covers only the **scraper**. It reads product catalogs from stores
and stores them in PostgreSQL. It runs as a Kubernetes CronJob on Azure Kubernetes Service (AKS, Free
tier). (Changed on 2026-11-10 from a local k3d cluster: managed Kubernetes
is what jobs ask for.)

## Scope

In scope:

- A store list in `stores.yaml`.
- One platform reader: **Shopify** (for example kaboa.com.uy).
- A common product format, saved to PostgreSQL with upserts.
- Marking products that disappear from a store as removed (no delete).
- A run log per store.
- Polite HTTP: rate limit, retries, an identifying user agent, robots.txt.
- A command-line tool with a `--dry-run` mode that prints products without a
  database.
- A Dockerfile and Kubernetes files: CronJob, ConfigMap, Secret, and a
  single-instance PostgreSQL StatefulSet.
- Tests that never call real stores.

Out of scope (later stages): Ecwid, Tiendanube and WooCommerce readers;
style tagging; queue and workers; search; downloading images; Helm; AKS.

## Repository layout

```
ropa-uy/
  services/scraper/
    scraper/
      __main__.py      CLI entry point
      config.py        load and validate stores.yaml and env vars
      models.py        Product, StoreConfig dataclasses
      http.py          polite HTTP client
      platforms/
        __init__.py    platform name -> reader lookup
        shopify.py
      db.py            schema setup, upsert, mark removed, run log
      schema.sql
      run.py           orchestrates one run across stores
    tests/
      fixtures/        saved sample responses
    stores.yaml
    requirements.txt       runtime dependencies (used by the Dockerfile)
    requirements-dev.txt   adds pytest
    pyproject.toml         pytest settings
    Dockerfile
  deploy/
    aks/               YAML manifests + kustomization.yaml for stage 1
  docs/
```

## Store list

```yaml
stores:
  - slug: kaboa
    name: Kaboa
    url: https://www.kaboa.com.uy
    platform: shopify
    currency: UYU          # Shopify's products.json does not include currency
    audience: unisex       # men | unisex | mixed
    collections: []        # for mixed stores: scrape only these collections
```

Validation runs at startup: each slug must be unique and lowercase, the
platform must have a reader, the URL must be https, and `collections` is
required when `audience` is `mixed`. Invalid config stops the run before any
request.

## Product format

| Field | Type | Notes |
|---|---|---|
| store_slug | text | from config |
| external_id | text | platform product id |
| title | text | |
| url | text | product page |
| price | numeric(12,2) | lowest price among available variants, else lowest overall |
| currency | char(3) | from config |
| sizes | text[] | sizes with an available variant |
| in_stock | bool | any variant available |
| image_urls | text[] | URLs only, not downloaded |
| vendor, product_type | text | as the store reports them |
| tags | text[] | the store's own tags (used for style tagging later) |
| raw | jsonb | the original product payload, for later reprocessing |

**Shopify reader.** It reads `{url}/products.json?limit=250&page=N` (or
`{url}/collections/{handle}/products.json` for each configured collection).
It stops at the first empty page and stops after 100 pages as a safety
limit. For sizes, it uses the option whose name matches
`talle|talla|size|tamaño` (case-insensitive). If there is no such option,
`sizes` is empty.

## Database

`schema.sql` is applied at every start with `CREATE TABLE IF NOT EXISTS`, so
it can run any number of times. Migrations with a proper tool come in a later
stage.

- `products`: the fields above, plus `first_seen_at`, `last_seen_at` and a
  nullable `removed_at`. `UNIQUE (store_slug, external_id)`.
- `scrape_runs`: `id`, `store_slug`, `started_at`, `finished_at`, `status`
  (`running`, `ok` or `failed`), `products_seen` and `error`.

**Upsert.** It inserts new products, updates existing ones, sets
`last_seen_at` to the current run time, and clears `removed_at` (a product
that comes back is live again).

**Removal.** Only after a **successful** run for a store, it marks that
store's products with `last_seen_at < run start` and `removed_at IS NULL` as
removed. A failed run marks nothing, so an outage doesn't make every product
look gone.

## HTTP behaviour

- `httpx` client with a 20-second timeout.
- At most one request per second to each host (configurable).
- Retries on network errors, 429 and 5xx: 3 attempts, with exponential
  backoff starting at 2 seconds.
- User agent: `ropa-uy-bot/0.1 (+<contact URL from env>)`.
- `robots.txt` is checked once per host with `urllib.robotparser`. Disallowed
  paths are skipped and logged. If robots.txt can't be read (404), crawling
  is allowed. Any other error stops scraping of that store for the run.

## Run behaviour

```
python -m scraper run [--store SLUG] [--dry-run]
```

- Stores are scraped one at a time. A failing store is logged and recorded in
  `scrape_runs`, and the run moves on to the next store.
- Exit code is 0 if every store succeeded, 1 if any failed, so a Kubernetes
  Job shows the failure.
- `--dry-run` skips the database and prints products as JSON lines. It's for
  development and learning.
- Logs go to stdout, one line per event, in a key=value style that
  `kubectl logs` shows well.

Environment variables: `DATABASE_URL` (required unless dry run),
`STORES_FILE` (default `stores.yaml`), `CONTACT_URL`, `REQUESTS_PER_SECOND`
(default 1).

## Kubernetes (stage 1, AKS)

- Namespace `ropa-uy`.
- `postgres`: a StatefulSet with 1 replica and a 1Gi PVC (AKS default storage class, an Azure Disk), a
  headless Service, and the password in a Secret.
- `scraper`: a CronJob every 6 hours with `concurrencyPolicy: Forbid`,
  `backoffLimit: 1` and `ttlSecondsAfterFinished` of 1 day. `stores.yaml`
  comes from a ConfigMap, `DATABASE_URL` from a Secret. It runs as a
  non-root user with small resource requests and limits.
- The image is built with `az acr build` into Azure Container Registry, which
  the cluster pulls from (AcrPull). `kustomization.yaml` sets the registry name.
- The Azure resources are listed in `docs/infra.md`; Gonzalo creates them.
- The database Secret is created with `kubectl create secret` and never
  committed to Git.

## Testing

- pytest. HTTP is mocked with `httpx.MockTransport`, so there are no extra
  dependencies and no real network calls.
- Shopify reader tests use saved sample responses: pagination, collections,
  size detection, price and stock rules, and an empty catalog.
- Config validation tests cover each rule above.
- HTTP client tests cover retry on 429/5xx, giving up after 3 attempts,
  robots.txt blocking, and the rate limit (with a fake clock).
- Database tests (upsert, return after removal, removal only after a
  successful run) run against a real PostgreSQL. They are skipped unless
  `TEST_DATABASE_URL` is set.

## Dependencies

Runtime: `httpx`, `PyYAML`, `psycopg[binary]` (v3). Dev: `pytest`.
Python 3.12.
