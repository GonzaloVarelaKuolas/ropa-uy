-- Applied at every start. Safe to run any number of times.

CREATE TABLE IF NOT EXISTS products (
    id             bigserial PRIMARY KEY,
    store_slug     text          NOT NULL,
    external_id    text          NOT NULL,
    title          text          NOT NULL,
    url            text          NOT NULL,
    price          numeric(12,2),
    currency       char(3)       NOT NULL,
    sizes          text[]        NOT NULL DEFAULT '{}',
    in_stock       boolean       NOT NULL,
    image_urls     text[]        NOT NULL DEFAULT '{}',
    vendor         text,
    product_type   text,
    tags           text[]        NOT NULL DEFAULT '{}',
    raw            jsonb         NOT NULL,
    first_seen_at  timestamptz   NOT NULL,
    last_seen_at   timestamptz   NOT NULL,
    removed_at     timestamptz,
    UNIQUE (store_slug, external_id)
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id             bigserial PRIMARY KEY,
    store_slug     text          NOT NULL,
    started_at     timestamptz   NOT NULL DEFAULT now(),
    finished_at    timestamptz,
    status         text          NOT NULL CHECK (status IN ('running', 'ok', 'failed')),
    products_seen  integer       NOT NULL DEFAULT 0,
    error          text
);
