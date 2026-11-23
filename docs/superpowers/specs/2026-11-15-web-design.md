# Website 1.0: design

Date: 2026-11-15
Status: built

## What it is

The public site for ropa-uy: a catalog of the products the scraper stores,
with search and filters, a product page that links out to the store, and a
stores page. It is read-only: the scraper owns the tables, the website only
runs SELECTs.

## Decisions

- **Rendered on the server** (FastAPI + Jinja2). Every state of the catalog is
  a URL, so pages can be shared and indexed by search engines, and the site
  works without JavaScript. `app.js` only auto-applies filters on change.
- **One Python service** in `services/web/`, with its own image and Deployment.
  It shares nothing with the scraper's code, only the database tables.
- **Spanish interface**, Uruguayan price format (`$ 1.668`).
- **Categories come from the title** (regex per category in `catalog.py`),
  because stores rarely fill in a product type. Style tags (urban, punk…)
  are stage 3.
- **Sale prices** come from the store's pre-discount price in the saved raw
  payload (`compare_at_price` on Shopify), computed in SQL at read time.
- **Images are loaded from the store's CDN**, resized by URL for Shopify.
  Nothing is downloaded or stored (stage 4 moves images to S3).
- **Outbound links carry `utm_source=ropa-uy`**, so stores can see the visits
  we send them.
- **Fonts are bundled** (Archivo, IBM Plex Mono; open licences). No external
  requests besides product images.
- **Not public yet**: the Service is internal; use `kubectl port-forward`.
  An Ingress with HTTPS is stage 2.

## Pages

| Path | What it shows |
|---|---|
| `/` | Catalog: search (`q`), category (`cat`), store (`tienda`), size (`talle`), price (`min`, `max`), in stock (`stock=1`), on sale (`oferta=1`), order (`orden`), page (`pagina`); 48 per page |
| `/p/{id}` | Product: photos, price, sizes in stock, link to the store, more from the store. Removed products stay visible, marked as unavailable |
| `/tiendas` | Stores with product counts and last update |
| `/healthz` | Liveness: the process is up |
| `/readyz` | Readiness: the database answers (503 if not) |

Errors: an unknown page or product gives a friendly 404; a database outage
gives a friendly 503; a database the scraper has never filled shows an empty
catalog instead of an error.

## Out of scope for 1.0

Accounts, favourites, price history, price alerts, style tags, a search
engine (PostgreSQL `ILIKE` is enough at this size), a public address.
