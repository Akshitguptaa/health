"""Runs against a real Postgres (DATABASE_URL). Skipped when none is reachable.

Rows inserted here are synthetic test rows (state code 99) and are removed afterwards.
"""
import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.migrate import migrate

URL = os.getenv("DATABASE_URL")


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
]


@pytest.fixture(scope="module")
def client():
    migrate(URL)
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute("INSERT INTO states (code, name) VALUES ('99', 'Testland') ON CONFLICT DO NOTHING")
        did = c.execute(
            "INSERT INTO districts (state_code, lgd_code, name) VALUES ('99', '1', 'Test District')"
            " ON CONFLICT (state_code, lgd_code) DO UPDATE SET name = EXCLUDED.name RETURNING id"
        ).fetchone()[0]
        c.execute("INSERT INTO ownership_types VALUES ('P', 'Private') ON CONFLICT DO NOTHING")
        for fid, name, total, icu in [
            ("IN9900000001", "Sunrise Heart Hospital", 100, 10),
            ("IN9900000002", "Green Valley Clinic", 5, 0),
        ]:
            c.execute(
                "INSERT INTO facilities (facility_id, name, status, ownership_code, state_code, district_id, pincode)"
                " VALUES (%s, %s, 'Approved', 'P', '99', %s, '110001') ON CONFLICT DO NOTHING",
                (fid, name, did),
            )
            c.execute(
                "INSERT INTO facility_infrastructure (facility_id, total_beds, icu_beds, has_icu)"
                " VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (fid, total, icu, icu > 0),
            )
    from app.main import app

    with TestClient(app) as c:
        yield c
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute("DELETE FROM facilities WHERE state_code = '99'")
        c.execute("DELETE FROM districts WHERE state_code = '99'")
        c.execute("DELETE FROM states WHERE code = '99'")


def test_health_confirms_database(client):
    assert client.get("/health").json() == {"status": "ok", "database": "up"}


def test_typo_tolerant_name_search(client):
    r = client.get("/api/facilities", params={"state": "99", "name": "hart"})
    assert r.status_code == 200
    assert [f["facilityId"] for f in r.json()["facilities"]] == ["IN9900000001"]


def test_icu_filter_and_sort_by_beds(client):
    r = client.get("/api/facilities", params={"state": "99", "icu": "yes"})
    assert r.json()["totalFacilities"] == 1
    r = client.get("/api/facilities", params={"state": "99", "sort": "beds"})
    assert [f["facilityId"] for f in r.json()["facilities"]] == ["IN9900000001", "IN9900000002"]


def test_facility_id_ignores_other_filters(client):
    r = client.get("/api/facilities", params={"facilityId": "IN9900000002", "name": "zzz", "icu": "yes"})
    assert r.json()["totalFacilities"] == 1


def test_stats_counts_beds(client):
    body = client.get("/api/stats").json()
    assert body["totalBeds"] >= 105
