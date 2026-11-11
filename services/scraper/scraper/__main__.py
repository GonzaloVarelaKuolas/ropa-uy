"""Command line: python -m scraper run [--store SLUG] [--dry-run]"""

import argparse
import os
import sys
from collections.abc import Mapping

from scraper import db, platforms
from scraper.config import ConfigError, load_settings, load_stores
from scraper.http import PoliteClient
from scraper.run import DbSink, PrintSink, log, run_stores

EXIT_OK, EXIT_STORE_FAILED, EXIT_CONFIG = 0, 1, 2


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scraper")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="scrape the stores in stores.yaml")
    run.add_argument("--store", help="only scrape the store with this slug")
    run.add_argument("--dry-run", action="store_true", help="print products instead of saving them")
    args = parser.parse_args(argv)
    env = os.environ if env is None else env

    try:
        settings = load_settings(env, dry_run=args.dry_run)
        stores = load_stores(settings.stores_file, platforms.READERS)
        if args.store:
            stores = [s for s in stores if s.slug == args.store]
            if not stores:
                raise ConfigError(f"no store with slug '{args.store}' in {settings.stores_file}")
    except ConfigError as exc:
        log("config_error", error=str(exc))
        return EXIT_CONFIG

    client = PoliteClient(settings.contact_url, settings.requests_per_second)
    conn = None
    try:
        if args.dry_run:
            sink = PrintSink()
        else:
            try:
                conn = db.connect(settings.database_url)
                db.apply_schema(conn)
                conn.commit()
            except Exception as exc:
                log("database_error", error=str(exc).strip())
                return EXIT_STORE_FAILED
            sink = DbSink(conn)
        results = run_stores(stores, client, platforms.READERS, sink)
    finally:
        client.close()
        if conn is not None:
            conn.close()

    failed = [r for r in results if not r.ok]
    log("run_finished", ok=len(results) - len(failed), failed=len(failed))
    return EXIT_STORE_FAILED if failed else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
