"""Read-only Health Facility Finder API.  Run: uvicorn app.main:app"""
from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .config import get_settings
from .errors import ApiError, install_error_handlers
from .ratelimit import RateLimiter, client_ip
from .search import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    SearchParams,
    build_query,
    count_sql,
    number_of_pages,
    page_sql,
)

FACILITY_ID_RE = re.compile(r"^IN[0-9]{10}$", re.IGNORECASE)

# URL segment -> (table, column that holds the code or None, label)
MASTER_TYPES = {
    "ownership": ("ownership_types", "code"),
    "facility-types": ("facility_types", "code"),
    "systems-of-medicine": ("systems_of_medicine", "code"),
    "specialities": ("specialities", None),
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    db.close_pool()


app = FastAPI(
    title="Health Facility Finder API",
    version="1.0.0",
    description="Read-only API over facility data scraped from the public NHPR facility search.",
    lifespan=lifespan,
)
install_error_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)
_limiter = RateLimiter(get_settings().search_rate_limit_per_min)


def rate_limit(request: Request) -> None:
    _limiter.check(client_ip(request))


# ---------- helpers ----------
def facility_json(r: dict[str, Any], detail: bool = False) -> dict[str, Any]:
    """Shape a DB row like the HFR search response (see brief, Appendix B)."""
    out = {
        "facilityId": r["facility_id"].strip(),
        "facilityName": r["name"],
        "facilityStatus": r["status"],
        "ownership": r["ownership"],
        "ownershipCode": r["ownership_code"],
        "facilityType": r["facility_type"],
        "facilityTypeCode": r["facility_type_code"],
        "systemOfMedicine": r["system_of_medicine"],
        "systemOfMedicineCode": r["som_code"],
        "stateName": r["state_name"],
        "stateLGDCode": r["state_code"].strip(),
        "districtName": r["district_name"],
        "districtLGDCode": r["district_code"],
        "address": r["address"],
        "pincode": r["pincode"],
        # HFR returns coordinates as strings; we store numbers and format on the way out.
        "latitude": None if r["latitude"] is None else str(r["latitude"]),
        "longitude": None if r["longitude"] is None else str(r["longitude"]),
        "hasIcuBeds": "Yes" if r["has_icu"] else "No",
        "abdmSoftware": "Yes" if r["abdm_software"] else "No",
    }
    if detail:
        out.update(
            subDistrictName=r["sub_district_name"],
            subDistrictLGDCode=r["sub_district_code"],
            villageCityTownName=r["village_city_town"],
            totalBeds=r["total_beds"],
            icuBeds=r["icu_beds"],
            photoUrl=r["photo_url"],
        )
    return out


def search_params(
    state: str | None = Query(None, pattern=r"^[0-9]{1,2}$", description="State LGD code"),
    district: str | None = Query(None, max_length=10, description="District LGD code (use with state)"),
    subDistrict: str | None = Query(None, max_length=10),
    pincode: str | None = Query(None, pattern=r"^[0-9]{6}$"),
    name: str | None = Query(None, min_length=2, max_length=100),
    facilityId: str | None = Query(None, pattern=r"^[Ii][Nn][0-9]{10}$"),
    ownership: str | None = Query(None, max_length=10, description="Ownership code, e.g. P"),
    facilityType: str | None = Query(None, max_length=40, description="Facility type code"),
    systemOfMedicine: str | None = Query(None, max_length=40, description="System of medicine code"),
    speciality: str | None = Query(None, max_length=100),
    icu: str | None = Query(None, pattern=r"^(?i:yes|no)$"),
    status: str | None = Query(None, max_length=30),
    sort: str | None = Query(None, pattern=r"^(name|district|beds)$"),
    page: int = Query(1, ge=1, le=100000),
    pageSize: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> SearchParams:
    if state is not None:
        state = state.zfill(2)
    return SearchParams(
        state=state, district=district, subDistrict=subDistrict, pincode=pincode,
        name=name.strip() if name else None, facilityId=facilityId, ownership=ownership,
        facilityType=facilityType, systemOfMedicine=systemOfMedicine, speciality=speciality,
        icu=icu, status=status, sort=sort, page=page, pageSize=pageSize,
    )


# ---------- endpoints ----------
@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    """Liveness check that also confirms the database connection."""
    try:
        db.fetch_one("SELECT 1 AS ok")
    except Exception as exc:  # noqa: BLE001 - report any DB failure as 503
        raise ApiError(503, "database_unavailable", "Database connection failed.") from exc
    return {"status": "ok", "database": "up"}


@app.get("/api/facilities", tags=["facilities"], dependencies=[Depends(rate_limit)])
def search_facilities(p: SearchParams = Depends(search_params)) -> dict[str, Any]:
    """Search facilities. At least one filter is required; `facilityId` overrides the rest."""
    if not p.filter_names():
        raise ApiError(
            400, "missing_filter",
            "Provide at least one search filter (e.g. state, district, name, facilityId).",
        )
    q = build_query(p)
    total = db.fetch_one(*count_sql(q))["n"]
    rows = db.fetch_all(*page_sql(q, p.page, p.pageSize))
    return {
        "facilities": [facility_json(r) for r in rows],
        "totalFacilities": total,
        "numberOfPages": number_of_pages(total, p.pageSize),
        "message": "Request processed successfully" if total else "No facilities found",
    }


@app.get("/api/facilities/{facility_id}", tags=["facilities"])
def get_facility(facility_id: str = Path(..., description="12-character HFR id, e.g. IN0310000334")) -> dict[str, Any]:
    if not FACILITY_ID_RE.match(facility_id):
        raise ApiError(400, "invalid_request", "facilityId must look like IN0310000334.")
    q = build_query(SearchParams(facilityId=facility_id))
    rows = db.fetch_all(*page_sql(q, 1, 1))
    if not rows:
        raise ApiError(404, "not_found", f"No facility with id {facility_id.upper()}.")
    out = facility_json(rows[0], detail=True)
    specs = db.fetch_all(
        "SELECT sp.name FROM facility_specialities fs JOIN specialities sp ON sp.id = fs.speciality_id"
        " WHERE fs.facility_id = %s ORDER BY sp.name",
        [facility_id.upper()],
    )
    out["specialities"] = [s["name"] for s in specs]
    return out


@app.get("/api/masters/states", tags=["masters"])
def list_states() -> list[dict[str, str]]:
    rows = db.fetch_all("SELECT code, name FROM states ORDER BY name")
    return [{"stateLGDCode": r["code"].strip(), "stateName": r["name"]} for r in rows]


@app.get("/api/masters/states/{state_code}/districts", tags=["masters"])
def list_districts(state_code: str = Path(..., pattern=r"^[0-9]{1,2}$")) -> list[dict[str, str]]:
    code = state_code.zfill(2)
    if not db.fetch_one("SELECT 1 AS ok FROM states WHERE code = %s", [code]):
        raise ApiError(404, "not_found", f"Unknown state code {code}.")
    rows = db.fetch_all(
        "SELECT lgd_code, name FROM districts WHERE state_code = %s ORDER BY name", [code]
    )
    return [{"districtLGDCode": r["lgd_code"], "districtName": r["name"]} for r in rows]


@app.get("/api/masters/{master_type}", tags=["masters"])
def list_master(
    master_type: str = Path(..., description="ownership | facility-types | systems-of-medicine | specialities"),
) -> list[dict[str, str]]:
    if master_type not in MASTER_TYPES:
        raise ApiError(
            404, "not_found",
            f"Unknown master '{master_type}'. Use one of: {', '.join(MASTER_TYPES)}.",
        )
    table, code_col = MASTER_TYPES[master_type]
    cols = "code, name" if code_col else "name"
    rows = db.fetch_all(f"SELECT {cols} FROM {table} ORDER BY name")  # table is from a fixed allow-list
    return [{"code": r["code"], "name": r["name"]} if code_col else {"name": r["name"]} for r in rows]


@app.get("/api/stats", tags=["stats"])
def stats() -> dict[str, Any]:
    totals = db.fetch_one(
        "SELECT count(*) AS facilities,"
        " COALESCE(sum(i.total_beds), 0) AS total_beds,"
        " COALESCE(sum(i.icu_beds), 0) AS icu_beds"
        " FROM facilities f LEFT JOIN facility_infrastructure i USING (facility_id)"
    )
    by_state = db.fetch_all(
        "SELECT s.code, s.name, count(*) AS n FROM facilities f JOIN states s ON s.code = f.state_code"
        " GROUP BY s.code, s.name ORDER BY n DESC, s.name"
    )
    by_type = db.fetch_all(
        "SELECT COALESCE(t.name, 'Unknown') AS name, count(*) AS n FROM facilities f"
        " LEFT JOIN facility_types t ON t.code = f.facility_type_code GROUP BY 1 ORDER BY n DESC"
    )
    by_owner = db.fetch_all(
        "SELECT COALESCE(o.name, 'Unknown') AS name, count(*) AS n FROM facilities f"
        " LEFT JOIN ownership_types o ON o.code = f.ownership_code GROUP BY 1 ORDER BY n DESC"
    )
    return {
        "totalFacilities": totals["facilities"],
        "totalBeds": int(totals["total_beds"]),
        "totalIcuBeds": int(totals["icu_beds"]),
        "byState": [{"stateLGDCode": r["code"].strip(), "stateName": r["name"], "count": r["n"]} for r in by_state],
        "byFacilityType": [{"name": r["name"], "count": r["n"]} for r in by_type],
        "byOwnership": [{"name": r["name"], "count": r["n"]} for r in by_owner],
    }
