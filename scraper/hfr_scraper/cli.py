"""Command line entry point.

    python -m hfr_scraper ingest data/raw          # load saved JSON captures (verified path)
    python -m hfr_scraper crawl --state 32 --district 590 --pages 3   # live, human types captcha
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

import psycopg

from .client import BlockedError, PoliteClient, build_search_params, make_captcha_token
from .parsers import total_pages
from .pipeline import Loader, ingest_path
from .report import RunStats
from .store import Store

ROBOTS_URL = "https://nhpr.abdm.gov.in/nhpr/v4/robots.txt"


def _database_url() -> str:
    return os.getenv("DATABASE_URL", "postgresql://hfr:hfr@localhost:5432/hfr")


def cmd_ingest(args: argparse.Namespace) -> int:
    stats = RunStats()
    with psycopg.connect(_database_url()) as conn:
        store = Store(conn)
        run_id = store.start_run()
        loader = Loader(store, stats)
        ingest_path(store, loader, Path(args.path), force=args.force)
        store.finish_run(run_id, stats.finish().as_dict())
    print(stats.finish().format())
    return 0


def cmd_crawl(args: argparse.Namespace) -> int:
    stats = RunStats()
    base = os.getenv("NHPR_API_BASE", "https://apinhpr.abdm.gov.in/v4/hfr")
    client = PoliteClient(
        base_url=base,
        user_agent=os.getenv("SCRAPER_USER_AGENT", "HealthFacilityFinderBot/0.1"),
        api_key=os.getenv("NHPR_API_KEY", ""),
        delay_s=float(os.getenv("SCRAPER_DELAY_SECONDS", "2.0")),
        stats=stats,
    )
    try:
        client.load_robots(ROBOTS_URL)
        with psycopg.connect(_database_url()) as conn:
            store = Store(conn)
            run_id = store.start_run()
            loader = Loader(store, stats)
            page, last_page = 1, args.pages
            while page <= last_page:
                unit = f"{args.state}:{args.district}:page={page}"
                if store.is_done(unit):  # resume: finished pages are never refetched
                    stats.pages_skipped += 1
                    page += 1
                    continue
                token = _ask_captcha(client)
                payload = client.get_json(
                    f"{client.base_url}/search/searchFacility",
                    params=build_search_params(args.state, args.district, page),
                    headers={"Authorization": f"Captcha_{token}"},
                )
                loader.load_payload("search_page", unit, payload)
                store.mark_done(unit)
                conn.commit()  # commit per page so an interrupted run keeps its progress
                reported = total_pages(payload)
                if reported:
                    last_page = min(last_page, reported)
                page += 1
            store.finish_run(run_id, stats.finish().as_dict())
    except BlockedError as exc:
        print(f"STOPPED: {exc}", file=sys.stderr)
        print(stats.finish().format())
        return 2
    print(stats.finish().format())
    return 0


def _ask_captcha(client: PoliteClient) -> str:
    """Show the captcha image and let a human read it. We never try to solve it."""
    data = client.get_json("https://apinhpr.abdm.gov.in/v4/cm/captcha/generate")
    Path("captcha.png").write_bytes(base64.b64decode(data["captcha"]))
    answer = input("Open captcha.png and type the digits: ").strip()
    return make_captcha_token(data["captchaId"], answer)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hfr_scraper", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_ing = sub.add_parser("ingest", help="load saved JSON responses from a file or folder")
    p_ing.add_argument("path")
    p_ing.add_argument("--force", action="store_true", help="reload files already loaded")
    p_ing.set_defaults(func=cmd_ingest)

    p_crawl = sub.add_parser("crawl", help="(experimental) fetch result pages live")
    p_crawl.add_argument("--state", required=True, help="state LGD code, e.g. 32")
    p_crawl.add_argument("--district", required=True, help="district LGD code")
    p_crawl.add_argument("--pages", type=int, default=1, help="max pages to fetch")
    p_crawl.set_defaults(func=cmd_crawl)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
