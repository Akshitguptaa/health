"""HTTP-level tests of two endpoints (GET /api/facilities, GET /api/facilities/{id})
plus validation and rate limiting. The database layer is stubbed, so these run
without Postgres; tests/test_api_db.py covers the real database."""
import pytest
from fastapi.testclient import TestClient

from app import db, main
from app.ratelimit import RateLimiter

ROW = {
    "facility_id": "IN3200004821", "name": "Example Heart and Multispeciality Hospital",
    "status": "Approved", "ownership_code": "P", "ownership": "Private",
    "facility_type_code": "HOSP", "facility_type": "Hospital",
    "som_code": "MM", "system_of_medicine": "Modern Medicine",
    "state_code": "32", "state_name": "Kerala", "district_code": "590", "district_name": "Kollam",
    "sub_district_code": None, "sub_district_name": None, "village_city_town": None,
    "address": "12 Example Road, Chinnakada", "pincode": "691001",
    "latitude": "8.885000", "longitude": "76.590000", "abdm_software": True,
    "photo_url": None, "has_icu": True, "total_beds": 50, "icu_beds": 8,
}


@pytest.fixture()
def client(monkeypatch):
    main._limiter = RateLimiter(limit=1000)
    return TestClient(main.app, raise_server_exceptions=False)


def test_search_returns_hfr_shaped_response(client, monkeypatch):
    monkeypatch.setattr(db, "fetch_one", lambda sql, args=(): {"n": 37})
    monkeypatch.setattr(db, "fetch_all", lambda sql, args=(): [ROW])
    r = client.get("/api/facilities", params={"state": "32", "name": "heart", "page": 1, "pageSize": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["totalFacilities"] == 37
    assert body["numberOfPages"] == 4
    assert body["message"] == "Request processed successfully"
    f = body["facilities"][0]
    assert f["facilityId"] == "IN3200004821"
    assert f["hasIcuBeds"] == "Yes" and f["abdmSoftware"] == "Yes"
    assert f["latitude"] == "8.885000"  # strings, like HFR


def test_empty_search_is_rejected_with_400_and_consistent_error_body(client):
    r = client.get("/api/facilities")
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "missing_filter"
    assert "at least one" in err["message"].lower()


@pytest.mark.parametrize(
    "params",
    [{"pincode": "12345"}, {"pageSize": 51}, {"page": 0}, {"icu": "maybe"}, {"sort": "price"}, {"state": "abc"}],
)
def test_invalid_input_returns_400_with_field_details(client, params):
    r = client.get("/api/facilities", params={"state": "32", **params} if "state" not in params else params)
    assert r.status_code == 400
    body = r.json()["error"]
    assert body["code"] == "invalid_request"
    assert body["details"]


def test_facility_detail_includes_beds_and_specialities(client, monkeypatch):
    calls = iter([[ROW], [{"name": "Cardiology"}, {"name": "Paediatrics"}]])
    monkeypatch.setattr(db, "fetch_all", lambda sql, args=(): next(calls))
    r = client.get("/api/facilities/in3200004821")
    assert r.status_code == 200
    body = r.json()
    assert body["totalBeds"] == 50 and body["icuBeds"] == 8
    assert body["specialities"] == ["Cardiology", "Paediatrics"]


def test_unknown_facility_returns_404(client, monkeypatch):
    monkeypatch.setattr(db, "fetch_all", lambda sql, args=(): [])
    r = client.get("/api/facilities/IN9999999999")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_malformed_facility_id_returns_400(client):
    assert client.get("/api/facilities/not-an-id").status_code == 400


def test_unknown_master_type_returns_404(client):
    r = client.get("/api/masters/colours")
    assert r.status_code == 404


def test_search_is_rate_limited(monkeypatch):
    main._limiter = RateLimiter(limit=2)
    monkeypatch.setattr(db, "fetch_one", lambda sql, args=(): {"n": 0})
    monkeypatch.setattr(db, "fetch_all", lambda sql, args=(): [])
    c = TestClient(main.app, raise_server_exceptions=False)
    assert c.get("/api/facilities", params={"state": "32"}).status_code == 200
    assert c.get("/api/facilities", params={"state": "32"}).status_code == 200
    third = c.get("/api/facilities", params={"state": "32"})
    assert third.status_code == 429
    assert "Retry-After" in third.headers
    assert third.json()["error"]["code"] == "rate_limited"


def test_openapi_spec_is_served(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert "/api/facilities" in r.json()["paths"]


def test_health_reports_503_when_db_is_down(client, monkeypatch):
    def boom(sql, args=()):
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "fetch_one", boom)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "database_unavailable"
