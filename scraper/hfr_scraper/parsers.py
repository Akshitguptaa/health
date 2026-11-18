"""Turn fetched JSON (a search page or one facility's details) into flat raw
records. Pure functions, tested against saved fixtures: no network needed.

The field names follow Appendix A of the brief. Because the live response
shape could not be checked (the search is behind a captcha), each field accepts
a few plausible aliases and the list wrapper may be named in several ways."""
from __future__ import annotations

import re
from typing import Any

# canonical key -> accepted source keys, first match wins
ALIASES: dict[str, tuple[str, ...]] = {
    "facility_id": ("facilityId", "facilityID", "hfrId"),
    "name": ("facilityName", "name"),
    "status": ("facilityStatus", "status"),
    "ownership": ("ownership",),
    "ownership_code": ("ownershipCode",),
    "facility_type": ("facilityType",),
    "facility_type_code": ("facilityTypeCode",),
    "system_of_medicine": ("systemOfMedicine",),
    "som_code": ("systemOfMedicineCode",),
    "state_name": ("stateName",),
    "state_code": ("stateLGDCode", "stateLgdCode"),
    "district_name": ("districtName",),
    "district_code": ("districtLGDCode", "districtLgdCode"),
    "sub_district_name": ("subDistrictName",),
    "sub_district_code": ("subDistrictLGDCode", "subDistrictLgdCode"),
    "village_city_town": ("villageCityTownName", "villageCityTown"),
    "address": ("address",),
    "pincode": ("pincode", "pinCode"),
    "latitude": ("latitude",),
    "longitude": ("longitude",),
    "has_icu": ("hasIcuBeds", "icuServices"),
    "abdm_software": ("abdmSoftware",),
    "specialities": ("specialities", "specialties"),
    "total_beds": ("totalBeds",),
    "icu_beds": ("icuBeds",),
    "photo_url": ("photoUrl",),
}

LIST_KEYS = ("facilities", "content", "facilityList", "records")
WRAPPER_KEYS = ("data", "response", "result")


def extract_items(payload: Any) -> list[dict[str, Any]]:
    """Return the facility objects in a payload, whatever its wrapper.

    Also accepts a capture bundle ``{"captures": [page, page, ...]}`` as saved
    by scraper/browser/capture.js, or a plain list of such pages."""
    if isinstance(payload, list):
        items: list[dict[str, Any]] = []
        for element in payload:
            if not isinstance(element, dict):
                continue
            if any(k in element for k in (*LIST_KEYS, *WRAPPER_KEYS, "captures")):
                items.extend(extract_items(element))  # a whole page inside the list
            else:
                items.append(element)  # a facility object (validated later)
        return items
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("captures"), list):
        return extract_items(payload["captures"])
    for key in LIST_KEYS:
        if isinstance(payload.get(key), list):
            return [x for x in payload[key] if isinstance(x, dict)]
    for key in WRAPPER_KEYS:
        inner = payload.get(key)
        if isinstance(inner, (dict, list)):
            found = extract_items(inner)
            if found:
                return found
    # A single facility's details response.
    if any(k in payload for k in ALIASES["facility_id"]):
        return [payload]
    return []


def total_pages(payload: Any) -> int | None:
    """Number of result pages the payload reports, if it says."""
    if not isinstance(payload, dict):
        return None
    for source in (payload, *[payload.get(k) for k in WRAPPER_KEYS if isinstance(payload.get(k), dict)]):
        for key in ("numberOfPages", "totalPages"):
            value = source.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
    return None


# ---------------------------------------------------------------------------
# The real NHPR record shape (seen in a real capture, 2026-11-18)
# ---------------------------------------------------------------------------
OWNERSHIP_NAMES = {"P": "Private", "G": "Government"}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _latest(entries: Any) -> dict[str, Any]:
    """The most recently updated entry of a list of dicts (or {})."""
    rows = [e for e in entries or [] if isinstance(e, dict)]
    if not rows:
        return {}
    return max(rows, key=lambda e: str(e.get("lastUpdatedDate") or e.get("lstUpdDt") or ""))


def _split_geolocation(value: Any) -> tuple[str | None, str | None]:
    text = _text(value)
    if not text:
        return None, None
    parts = [p.strip() for p in text.split(",")]
    if len(parts) == 2:
        return parts[0], parts[1]
    return text, None  # malformed: validation will flag it as invalid_coordinates


def _systems(value: Any) -> str | None:
    """'Physiotherapy,Dentistry,Modern Medicine(Allopathy)' -> sorted, comma separated."""
    parts = sorted({p.strip() for p in str(value or "").split(",") if p.strip()})
    return ", ".join(parts) or None


def from_nhpr_record(item: dict[str, Any]) -> dict[str, Any]:
    """Map a real NHPR facility object onto canonical keys.

    Mapping decisions (all documented in the README):
    * facility id            <- alternateId  (facUniqueId is an internal number)
    * state code / district  <- nhrrStateCode / the location id (NOT an LGD code)
    * ownership name         <- derived from facOwnership: P = Private, G = Government
    * facility type          <- facilityType name; facilitySubtype is finer-grained, so unused
    * beds / ICU             <- the most recently updated medicalInfraRequestDTO entry
    * specialities           <- specialityDtls entries flagged activeYn == "Y"
    """
    state = item.get("state") if isinstance(item.get("state"), dict) else {}
    district = item.get("district") if isinstance(item.get("district"), dict) else {}
    infra = _latest(item.get("medicalInfraRequestDTO"))
    lat, lon = _split_geolocation(item.get("geolocation"))
    ownership_code = _text(item.get("facOwnership"))
    specialities = [
        _text(s.get("specName")) for s in item.get("specialityDtls") or []
        if isinstance(s, dict) and s.get("activeYn") == "Y" and _text(s.get("specName"))
    ]
    address = ", ".join(p for p in (_text(item.get("address1")), _text(item.get("address2"))) if p)
    raw = {
        "facility_id": item.get("alternateId"),
        "name": item.get("facName"),
        "status": item.get("status"),
        "ownership_code": ownership_code,
        "ownership": OWNERSHIP_NAMES.get((ownership_code or "").upper()),
        "facility_type": item.get("facilityType"),
        "system_of_medicine": _systems(item.get("systemOfMedicine")),
        "state_name": state.get("locName"),
        "state_code": state.get("nhrrStateCode") or state.get("locId"),
        "district_name": district.get("locName"),
        "district_code": district.get("locId"),
        "sub_district_code": item.get("subDistrict"),
        "village_city_town": item.get("vilCityTown"),
        "address": address or None,
        "pincode": item.get("pincode"),
        "latitude": lat,
        "longitude": lon,
        "has_icu": infra.get("hasIcuBeds"),
        "abdm_software": item.get("abdmSoftware"),
        "total_beds": infra.get("totalBeds"),
        "icu_beds": infra.get("icuBeds"),
        "specialities": specialities,
    }
    return {k: v for k, v in raw.items() if v is not None}


# ---------------------------------------------------------------------------
# Data minimisation: what we are willing to keep in raw_responses / quarantine
# ---------------------------------------------------------------------------
_PRIVATE_KEY = re.compile(
    r"email|mob|landline|contactper|facaltcontact|alternatecontact|^healthid$|usr$|password|"
    r"surname|middlename|^declaredby$|doctordeclaration|nameasinpancard|^fac(pan|tan|gst)$|"
    r"identificationno|addproof|buildimage|^photo|image$|^ufid$|^facowner(govt|private)$",
    re.IGNORECASE,
)
_MAX_STRING = 5000  # anything longer is an embedded blob (e.g. a base64 photo)


def sanitize(value: Any) -> Any:
    """Return a copy without personal contact details, user ids and embedded images.

    The brief's schema has no use for a contact person's name, e-mail or phone
    number, so they are never stored."""
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items() if not _PRIVATE_KEY.search(k)}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, str) and len(value) > _MAX_STRING:
        return None
    return value


def to_raw_record(item: dict[str, Any]) -> dict[str, Any]:
    """Map one source object onto canonical keys (values left untouched)."""
    if "alternateId" in item or "facName" in item:
        return from_nhpr_record(item)
    out: dict[str, Any] = {}
    for canonical, names in ALIASES.items():
        for name in names:
            if name in item and item[name] is not None:
                out[canonical] = item[name]
                break
    return out
