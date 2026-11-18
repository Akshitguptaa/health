"""Idempotency and quarantine against a real Postgres. Skipped without DATABASE_URL."""
import os
from pathlib import Path

import psycopg
import pytest

from app.migrate import migrate
from hfr_scraper.pipeline import Loader, ingest_path
from hfr_scraper.report import RunStats
from hfr_scraper.store import Store

URL = os.getenv("DATABASE_URL")
FIXTURES = Path(__file__).parent / "fixtures"


def _reachable() -> bool:
    if not URL:
        return False
    try:
        psycopg.connect(URL, connect_timeout=3).close()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _reachable(), reason="no reachable Postgres in DATABASE_URL"),
    # This test EMPTIES the facility tables, so it must be opted into explicitly
    # and only pointed at a throwaway database.
    pytest.mark.skipif(
        os.getenv("HFR_TEST_ALLOW_WIPE") != "1",
        reason="set HFR_TEST_ALLOW_WIPE=1 (this test empties the facility tables)",
    ),
]


def snapshot(conn):
    tables = ["facilities", "facility_specialities", "facility_infrastructure", "quarantine", "raw_responses"]
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}


WIPE = ("facility_specialities", "facility_infrastructure", "facilities", "specialities", "sub_districts",
        "districts", "states", "ownership_types", "facility_types", "systems_of_medicine",
        "quarantine", "raw_responses", "crawl_progress", "scrape_runs")


def wipe(conn):
    conn.execute("TRUNCATE " + ", ".join(WIPE) + " RESTART IDENTITY CASCADE")
    conn.commit()


@pytest.fixture()
def clean_database():
    """Start empty and leave the database empty: no synthetic rows are left behind."""
    migrate(URL)
    with psycopg.connect(URL) as conn:
        wipe(conn)
    yield
    with psycopg.connect(URL) as conn:
        wipe(conn)


def test_loading_the_same_capture_twice_gives_identical_data(clean_database):
    with psycopg.connect(URL) as conn:
        stats1 = RunStats()
        ingest_path(Store(conn), Loader(Store(conn), stats1), FIXTURES / "search_page_synthetic.json")
        first = snapshot(conn)

        # force=True reloads even though the file is marked done: rows must not change.
        stats2 = RunStats()
        ingest_path(Store(conn), Loader(Store(conn), stats2), FIXTURES / "search_page_synthetic.json", force=True)
        second = snapshot(conn)

        assert first == second
        assert first["facilities"] == 2            # IN3200000001 (merged) and IN3200000002
        assert stats1.duplicates_merged == 1
        assert sum(stats1.rejected.values()) == 6  # each bad record quarantined, not dropped
        assert first["quarantine"] == 6

        # a normal rerun skips the file entirely
        stats3 = RunStats()
        ingest_path(Store(conn), Loader(Store(conn), stats3), FIXTURES / "search_page_synthetic.json")
        assert stats3.pages_skipped == 1 and stats3.pages_processed == 0

        specs = conn.execute(
            "SELECT array_agg(sp.name ORDER BY sp.name) FROM facility_specialities fs"
            " JOIN specialities sp ON sp.id = fs.speciality_id WHERE fs.facility_id = 'IN3200000001'"
        ).fetchone()[0]
        assert specs == ["Cardiology", "Orthopaedics", "Paediatrics"]
