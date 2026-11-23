<div align="center">

# 👕 ropa-uy

**Every men's clothing store in Uruguay, in one place, searchable by style.**

A learning-first project for running a real system on Kubernetes,
from a home lab to the cloud.

![Status](https://img.shields.io/badge/status-stage%201%20·%20building-yellow)
![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![Kubernetes](https://img.shields.io/badge/kubernetes-AKS-326CE5?logo=kubernetes&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/database-PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![Azure](https://img.shields.io/badge/cloud-AKS-0078D4?logo=microsoftazure&logoColor=white)
![AWS](https://img.shields.io/badge/images-S3-FF9900?logo=amazons3&logoColor=white)

</div>

---

## Why

Uruguayan men who want a particular style, such as urban, punk or
streetwear, usually find it only by already knowing the small brands on
Instagram. The big chains are easy to find. The independent labels are not.

**ropa-uy** reads the online catalogs of local stores, from small brands to
large chains, and brings them together so you can browse by style instead of
by store.

> **Project goals, in order**
> 1. Learn Kubernetes properly by building something real.
> 2. Keep it cheap enough that a small income from stores covers hosting.

## How it works

```mermaid
flowchart LR
    S[(stores.yaml)] --> C
    subgraph K8s[Kubernetes cluster]
        C[Scraper CronJob<br/>every 6h] -->|upsert| DB[(PostgreSQL)]
        DB --> W[Web app]
    end
    C -.->|products.json| ST1[Shopify stores]
    C -.-> ST2[Ecwid / Tiendanube /<br/>WooCommerce stores]
    U[Users] --> W
```

- **One reader per platform, not per store.** Most stores run on a handful
  of platforms, so adding a store is usually one line in `stores.yaml`.
- **Polite by design.** Rate-limited, follows `robots.txt`, and identifies
  itself with a contact URL.
- **Nothing is deleted.** Products that leave a store are marked removed, and
  only after a successful scrape.

## Roadmap

Each stage ends with a working site and adds new Kubernetes concepts.

| Stage | What gets built | What you learn |
|:-----:|-----------------|----------------|
| **1** | Shopify scraper, PostgreSQL, simple web app on **Azure AKS** (free tier) | Deployments, Services, CronJobs, ConfigMaps, Secrets, StatefulSets, PVCs |
| **2** | Queue and parallel workers, more platforms, Ingress, Helm charts | Scaling, Ingress, packaging with Helm |
| **3** | Style tagging, search engine, Prometheus + Grafana, Argo CD | Observability, GitOps |
| **4** | Product images on **AWS S3**, infra as code | Multi-cloud, Terraform |

**Current progress**

- [x] Stage 1 scraper design ([spec](docs/superpowers/specs/2026-11-07-scraper-design.md))
- [x] Stage 1 implementation plan ([plan](docs/superpowers/plans/2026-11-08-stage1-scraper.md))
- [x] Shopify scraper
- [x] AKS manifests (PostgreSQL + CronJob)
- [ ] AKS cluster and registry ([what to create](docs/infra.md))
- [x] Web app 1.0 (catalog, search, filters, product and store pages)

## Repository layout

```text
ropa-uy/
├── services/
│   ├── scraper/        # Python scraper (stage 1)
│   └── web/            # Web app (stage 1)
├── deploy/
│   └── aks/            # Kubernetes manifests (kubectl apply -k)
└── docs/
    └── superpowers/
        └── specs/      # Design documents
```

## Tech stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.12 (`httpx`, `psycopg` 3, `PyYAML`, `pytest`) |
| Website | FastAPI + Jinja2 templates, rendered on the server; plain CSS, almost no JavaScript |
| Database | PostgreSQL |
| Orchestration | Azure Kubernetes Service (AKS) |
| Object storage | AWS S3 (stage 4) |

## Getting started

### Run the scraper on your machine

```bash
cd services/scraper
python -m venv .venv && .venv\Scripts\activate     # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest                                    # database tests run only with TEST_DATABASE_URL set
python -m scraper run --dry-run --store kaboa       # prints products as JSON, saves nothing
```

### Run the website on your machine

It needs a PostgreSQL that the scraper has filled. With Docker Desktop running:

```bash
docker run -d --name ropa-pg -e POSTGRES_PASSWORD=dev -p 5432:5432 postgres:16-alpine
set DATABASE_URL=postgresql://postgres:dev@localhost:5432/postgres    # PowerShell: $env:DATABASE_URL="..."

cd services/scraper && python -m scraper run          # fills the database (use the scraper's venv)

cd ../web
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements-dev.txt
set STORES_FILE=..\scraper\stores.yaml
uvicorn web.app:app --reload                          # open http://localhost:8000
```

Pages: `/` (catalog with search, categories, filters by store, size, price, stock and offers),
`/p/<id>` (product, with a link out to the store), `/tiendas` (stores), `/healthz` and `/readyz`
(for Kubernetes probes). Tests: `python -m pytest` (database tests need `TEST_DATABASE_URL`).

### Deploy to AKS

First create the infrastructure listed in [docs/infra.md](docs/infra.md), then:

| # | Command | What it teaches |
|---|---------|-----------------|
| 1 | `az aks get-credentials -g rg-ropa-uy -n aks-ropa-uy` | Points `kubectl` at your cluster |
| 2 | `az acr build -r <acr> -t ropa-uy-scraper:0.1.0 services/scraper` | Builds the image in Azure and stores it in your registry |
| 2b | `az acr build -r <acr> -t ropa-uy-web:0.1.0 services/web` | Same, for the website image |
| 3 | Replace `ACR_NAME` in `deploy/aks/kustomization.yaml` | Kustomize rewrites image names without editing every file |
| 4 | `kubectl apply -f deploy/aks/namespace.yaml` | Namespaces group the project's objects |
| 5 | `kubectl -n ropa-uy create secret generic ropa-uy-db --from-literal=postgres-password=<pick one> --from-literal=database-url=postgresql://postgres:<same>@postgres:5432/postgres` | Secrets keep passwords out of Git |
| 6 | `kubectl -n ropa-uy create configmap scraper-stores --from-file=stores.yaml=services/scraper/stores.yaml` | ConfigMaps keep settings out of the image |
| 7 | `kubectl apply -k deploy/aks` | Creates PostgreSQL (with an Azure Disk), the scraper CronJob and the website Deployment |
| 8 | `kubectl -n ropa-uy get pods -w` | Wait for `postgres-0` to be `Running` and `1/1` ready |
| 9 | `kubectl -n ropa-uy create job --from=cronjob/scraper scraper-manual-1` | Runs the CronJob now instead of waiting 6 hours |
| 10 | `kubectl -n ropa-uy logs -f job/scraper-manual-1` | Ends with `event=run_finished ok=1 failed=0` |
| 11 | `kubectl -n ropa-uy exec -it postgres-0 -- psql -U postgres -c "select store_slug, count(*) from products group by 1;"` | Checks the data landed |
| 12 | `kubectl -n ropa-uy port-forward svc/web 8080:80` | Opens the site at http://localhost:8080 through a tunnel, without exposing it to the internet |

In step 5, use only letters and digits in the password: it goes inside a URL, where characters like `@`, `:` or `/` break it.

The website is not public yet: its Service is internal. Giving it a public address (an Ingress
with HTTPS) is the first step of stage 2.

To change the store list later: re-run step 6 with `--dry-run=client -o yaml | kubectl apply -f -` appended.

**Save money:** `az aks stop -g rg-ropa-uy -n aks-ropa-uy` when you're not using it, `az aks start` to resume.

## Database

PostgreSQL 16. The scraper creates the two tables it needs (`products` and
`scrape_runs`) by itself on every start. The full schema below adds indexes,
price history and the tables later stages will use. It is safe to run more
than once, and on a database that already has data.

| Table | What it stores | Status |
|---|---|---|
| `products` | One row per product per store: title, price, sizes, images, the store's raw data | In use |
| `scrape_runs` | One row per store per scraper run: result, product count, error | In use |
| `price_history` | Every price or stock change, recorded by a database trigger | Works once created; nothing reads it yet |
| `stores` | The store list (today in `stores.yaml`) | Planned, stage 2 |
| `styles`, `product_styles` | Style tags (urbano, punk…) per product | Planned, stage 3 |
| `outbound_clicks` | Clicks sent to each store, with no personal data | Planned |
| `users`, `favorites`, `price_alerts` | Accounts, saved products and "tell me when it drops below X" | Planned |

To apply it, copy the SQL into a file called `schema.sql` and run:

```bash
kubectl -n ropa-uy exec -i postgres-0 -- psql -U postgres < schema.sql     # on AKS
psql "$DATABASE_URL" -f schema.sql                                          # anywhere else
```

<details>
<summary><strong>Full schema (SQL)</strong></summary>

```sql
-- ropa-uy database schema (PostgreSQL 16)
-- Safe to run more than once. Run as:
--   kubectl -n ropa-uy exec -i postgres-0 -- psql -U postgres < schema.sql

CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- fast "contains" search on titles

-- ───────────────────────── In use today ─────────────────────────

-- One row per product per store. Written by the scraper, read by the website.
CREATE TABLE IF NOT EXISTS products (
    id             bigserial PRIMARY KEY,
    store_slug     text          NOT NULL,
    external_id    text          NOT NULL,           -- the store's own product id
    title          text          NOT NULL,
    url            text          NOT NULL,           -- product page on the store
    price          numeric(12,2),                    -- lowest price among variants in stock
    currency       char(3)       NOT NULL,
    sizes          text[]        NOT NULL DEFAULT '{}',   -- sizes in stock
    in_stock       boolean       NOT NULL,
    image_urls     text[]        NOT NULL DEFAULT '{}',
    vendor         text,
    product_type   text,
    tags           text[]        NOT NULL DEFAULT '{}',   -- the store's own tags
    raw            jsonb         NOT NULL,           -- original payload, for reprocessing
    first_seen_at  timestamptz   NOT NULL,
    last_seen_at   timestamptz   NOT NULL,
    removed_at     timestamptz,                      -- set when it disappears from the store
    UNIQUE (store_slug, external_id)
);

-- One row per store per scraper run: did it work, and how many products it saw.
CREATE TABLE IF NOT EXISTS scrape_runs (
    id             bigserial PRIMARY KEY,
    store_slug     text          NOT NULL,
    started_at     timestamptz   NOT NULL DEFAULT now(),
    finished_at    timestamptz,
    status         text          NOT NULL CHECK (status IN ('running', 'ok', 'failed')),
    products_seen  integer       NOT NULL DEFAULT 0,
    error          text
);

-- Indexes for the website's catalog queries.
CREATE INDEX IF NOT EXISTS products_live_newest_idx ON products (first_seen_at DESC) WHERE removed_at IS NULL;
CREATE INDEX IF NOT EXISTS products_live_price_idx  ON products (price)              WHERE removed_at IS NULL;
CREATE INDEX IF NOT EXISTS products_store_idx       ON products (store_slug);
CREATE INDEX IF NOT EXISTS products_title_trgm_idx  ON products USING gin (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS products_sizes_idx       ON products USING gin (sizes);
CREATE INDEX IF NOT EXISTS products_tags_idx        ON products USING gin (tags);
CREATE INDEX IF NOT EXISTS scrape_runs_store_idx    ON scrape_runs (store_slug, started_at DESC);

-- ───────────────── Price history (works as soon as it's created) ─────────────────

-- Every price or stock change of a product. Filled by the trigger below,
-- so the scraper needs no changes. Powers "lowest price in 30 days" and price alerts.
CREATE TABLE IF NOT EXISTS price_history (
    id           bigserial PRIMARY KEY,
    product_id   bigint        NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    price        numeric(12,2),
    in_stock     boolean       NOT NULL,
    recorded_at  timestamptz   NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS price_history_product_idx ON price_history (product_id, recorded_at DESC);

CREATE OR REPLACE FUNCTION record_price_change() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT'
       OR NEW.price IS DISTINCT FROM OLD.price
       OR NEW.in_stock IS DISTINCT FROM OLD.in_stock THEN
        INSERT INTO price_history (product_id, price, in_stock, recorded_at)
        VALUES (NEW.id, NEW.price, NEW.in_stock, NEW.last_seen_at);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS products_price_history ON products;
CREATE TRIGGER products_price_history
    AFTER INSERT OR UPDATE OF price, in_stock ON products
    FOR EACH ROW EXECUTE FUNCTION record_price_change();

-- ───────────────── Planned (created now, used by later stages) ─────────────────

-- Stores. Today they live in stores.yaml; this table replaces it when stores
-- are managed from the site (stage 2).
CREATE TABLE IF NOT EXISTS stores (
    slug        text PRIMARY KEY CHECK (slug ~ '^[a-z0-9][a-z0-9-]*$'),
    name        text        NOT NULL,
    url         text        NOT NULL CHECK (url LIKE 'https://%'),
    platform    text        NOT NULL,                 -- shopify, ecwid, tiendanube, woocommerce
    currency    char(3)     NOT NULL DEFAULT 'UYU',
    audience    text        NOT NULL DEFAULT 'unisex' CHECK (audience IN ('men', 'unisex', 'mixed')),
    collections text[]      NOT NULL DEFAULT '{}',    -- for mixed stores: which collections to read
    instagram   text,
    city        text,
    active      boolean     NOT NULL DEFAULT true,    -- false = stop scraping, keep the data
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Styles (urbano, punk, skater…) and which products have them (stage 3).
CREATE TABLE IF NOT EXISTS styles (
    slug  text PRIMARY KEY CHECK (slug ~ '^[a-z0-9][a-z0-9-]*$'),
    name  text NOT NULL
);

CREATE TABLE IF NOT EXISTS product_styles (
    product_id  bigint       NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    style_slug  text         NOT NULL REFERENCES styles (slug) ON DELETE CASCADE,
    source      text         NOT NULL CHECK (source IN ('rule', 'model', 'manual')),
    confidence  numeric(3,2) CHECK (confidence BETWEEN 0 AND 1),
    tagged_at   timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (product_id, style_slug)
);
CREATE INDEX IF NOT EXISTS product_styles_style_idx ON product_styles (style_slug);

-- Clicks on "Ver en la tienda". No personal data: this is the number you show
-- a store to prove the traffic you send them.
CREATE TABLE IF NOT EXISTS outbound_clicks (
    id          bigserial PRIMARY KEY,
    product_id  bigint      REFERENCES products (id) ON DELETE SET NULL,
    store_slug  text        NOT NULL,
    clicked_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS outbound_clicks_store_idx ON outbound_clicks (store_slug, clicked_at DESC);

-- Accounts, favourites and price alerts (the paid tier idea).
CREATE TABLE IF NOT EXISTS users (
    id             bigserial PRIMARY KEY,
    email          text        NOT NULL,
    password_hash  text,                              -- NULL when signing in with an email link
    created_at     timestamptz NOT NULL DEFAULT now(),
    last_login_at  timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS users_email_idx ON users (lower(email));

CREATE TABLE IF NOT EXISTS favorites (
    user_id     bigint      NOT NULL REFERENCES users (id)    ON DELETE CASCADE,
    product_id  bigint      NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, product_id)
);

CREATE TABLE IF NOT EXISTS price_alerts (
    id            bigserial PRIMARY KEY,
    user_id       bigint        NOT NULL REFERENCES users (id)    ON DELETE CASCADE,
    product_id    bigint        NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    target_price  numeric(12,2) NOT NULL CHECK (target_price > 0),  -- alert when price <= this
    size          text,                                             -- only if this size is in stock
    created_at    timestamptz   NOT NULL DEFAULT now(),
    notified_at   timestamptz,                                      -- NULL = still waiting
    UNIQUE (user_id, product_id)
);
CREATE INDEX IF NOT EXISTS price_alerts_pending_idx ON price_alerts (product_id) WHERE notified_at IS NULL;
```

</details>

## For store owners

ropa-uy reads only public catalog pages, sends each visitor straight to your
own store to buy, and follows your `robots.txt`. If you want your store
added, removed or corrected, please open an issue.

---

<div align="center">
<sub>Built in 🇺🇾 Uruguay, one Kubernetes concept at a time.</sub>
</div>
