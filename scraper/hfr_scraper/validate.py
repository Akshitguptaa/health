"""Clean, validate and merge facility records.

Rules mirror the database constraints so nothing is rejected only at load time.
A record that fails is returned with reasons and goes to the quarantine table.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, fields, replace
from decimal import Decimal, InvalidOperation
from typing import Any

FACILITY_ID_RE = re.compile(r"^IN[0-9]{10}$")


@dataclass
class Facility:
    facility_id: str
    name: str
    status: str = "Submitted"
    ownership_code: str | None = None
    ownership: str | None = None
    facility_type_code: str | None = None
    facility_type: str | None = None
    som_code: str | None = None
    system_of_medicine: str | None = None
    state_code: str = ""
    state_name: str | None = None
    district_code: str = ""
    district_name: str | None = None
    sub_district_code: str | None = None
    sub_district_name: str | None = None
    village_city_town: str | None = None
    address: str | None = None
    pincode: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    has_icu: bool = False
    abdm_software: bool = False
    total_beds: int | None = None
    icu_beds: int | None = None
    photo_url: str | None = None
    specialities: list[str] = field(default_factory=list)


# ---------- field normalisers ----------
def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def clean_name(value: Any) -> str | None:
    """Collapse whitespace; turn SHOUTING CAPS into Title Case."""
    text = clean_text(value)
    if text and text.isupper() and any(c.isalpha() for c in text):
        text = text.title()
    return text


def clean_pincode(value: Any) -> tuple[str | None, bool]:
    """Return (pincode, ok). Missing is fine; present-but-wrong is not."""
    text = clean_text(value)
    if text is None:
        return None, True
    digits = re.sub(r"\D", "", text)
    if re.fullmatch(r"[0-9]{6}", digits):
        return digits, True
    return None, False


def clean_state_code(value: Any) -> str | None:
    text = clean_text(value)
    if text is None or not text.isdigit() or len(text) > 2:
        return None
    return text.zfill(2)


def clean_decimal(value: Any) -> tuple[Decimal | None, bool]:
    text = clean_text(value)
    if text is None:
        return None, True
    try:
        return Decimal(text).quantize(Decimal("0.000001")), True
    except (InvalidOperation, ValueError):
        return None, False


def clean_int(value: Any) -> tuple[int | None, bool]:
    text = clean_text(value)
    if text is None:
        return None, True
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None, False
    if number != number.to_integral_value():
        return None, False
    return int(number), True


def to_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"yes", "y", "true", "1"}


def clean_specialities(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = value.split(",")
    names: list[str] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            item = item.get("name") or item.get("specialityName") or item.get("speciality")
        name = clean_text(item)
        if name and name.lower() not in {n.lower() for n in names}:
            names.append(name)
    return names


def code_from_name(name: str | None) -> str | None:
    if not name:
        return None
    return re.sub(r"[^A-Z0-9]", "", name.upper())[:60] or None


# ---------- validation ----------
def validate(raw: dict[str, Any]) -> tuple[Facility | None, list[str]]:
    """Return (facility, []) when clean, or (None, reasons) when rejected."""
    reasons: list[str] = []

    fid = (clean_text(raw.get("facility_id")) or "").upper()
    if not FACILITY_ID_RE.match(fid):
        reasons.append("invalid_facility_id")
    name = clean_name(raw.get("name"))
    if not name:
        reasons.append("missing_name")

    state_code = clean_state_code(raw.get("state_code"))
    if state_code is None and FACILITY_ID_RE.match(fid):
        state_code = fid[2:4]  # the id embeds the state LGD code
    if state_code is None:
        reasons.append("missing_state")
    elif FACILITY_ID_RE.match(fid) and fid[2:4] != state_code:
        reasons.append("state_code_mismatch")

    district_code = clean_text(raw.get("district_code"))
    if not district_code:
        reasons.append("missing_district")

    pincode, ok = clean_pincode(raw.get("pincode"))
    if not ok:
        reasons.append("invalid_pincode")

    lat, ok_lat = clean_decimal(raw.get("latitude"))
    lon, ok_lon = clean_decimal(raw.get("longitude"))
    if not (ok_lat and ok_lon):
        reasons.append("invalid_coordinates")
    else:
        if lat is not None and not Decimal(-90) <= lat <= Decimal(90):
            reasons.append("latitude_out_of_range")
        if lon is not None and not Decimal(-180) <= lon <= Decimal(180):
            reasons.append("longitude_out_of_range")
        if lat == 0 and lon == 0:  # a (0, 0) placeholder means "unknown"
            lat = lon = None

    total, ok_total = clean_int(raw.get("total_beds"))
    icu, ok_icu = clean_int(raw.get("icu_beds"))
    if not (ok_total and ok_icu):
        reasons.append("invalid_bed_count")
    else:
        if (total is not None and total < 0) or (icu is not None and icu < 0):
            reasons.append("negative_beds")
        elif total is not None and icu is not None and icu > total:
            reasons.append("icu_beds_exceed_total")

    if reasons:
        return None, reasons

    ownership = clean_text(raw.get("ownership"))
    ftype = clean_text(raw.get("facility_type"))
    som = clean_text(raw.get("system_of_medicine"))
    return (
        Facility(
            facility_id=fid,
            name=name or "",
            status=clean_text(raw.get("status")) or "Submitted",
            ownership_code=(clean_text(raw.get("ownership_code")) or code_from_name(ownership)),
            ownership=ownership,
            facility_type_code=(clean_text(raw.get("facility_type_code")) or code_from_name(ftype)),
            facility_type=ftype,
            som_code=(clean_text(raw.get("som_code")) or code_from_name(som)),
            system_of_medicine=som,
            state_code=state_code or "",
            state_name=clean_name(raw.get("state_name")),
            district_code=district_code or "",
            district_name=clean_name(raw.get("district_name")),
            sub_district_code=clean_text(raw.get("sub_district_code")),
            sub_district_name=clean_name(raw.get("sub_district_name")),
            village_city_town=clean_name(raw.get("village_city_town")),
            address=clean_text(raw.get("address")),
            pincode=pincode,
            latitude=lat,
            longitude=lon,
            has_icu=to_bool(raw.get("has_icu")) or bool(icu and icu > 0),
            abdm_software=to_bool(raw.get("abdm_software")),
            total_beds=total,
            icu_beds=icu,
            photo_url=clean_text(raw.get("photo_url")),
            specialities=clean_specialities(raw.get("specialities")),
        ),
        [],
    )


# ---------- de-duplication ----------
def merge(existing: Facility, new: Facility) -> Facility:
    """Merge two records that share a facility id.

    Rule: the id is the identity. For each field the newer record wins when it
    has a value, otherwise the older value is kept. Specialities are unioned,
    booleans are OR-ed (a facility that reports ICU anywhere has ICU).
    """
    merged = existing
    for f in fields(Facility):
        if f.name in {"specialities", "has_icu", "abdm_software", "facility_id"}:
            continue
        new_value = getattr(new, f.name)
        if new_value not in (None, ""):
            merged = replace(merged, **{f.name: new_value})
    seen = {s.lower() for s in existing.specialities}
    union = list(existing.specialities) + [s for s in new.specialities if s.lower() not in seen]
    return replace(
        merged,
        specialities=union,
        has_icu=existing.has_icu or new.has_icu,
        abdm_software=existing.abdm_software or new.abdm_software,
    )
