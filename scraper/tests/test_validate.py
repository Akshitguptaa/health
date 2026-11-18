import json
from decimal import Decimal
from pathlib import Path

import pytest

from hfr_scraper.parsers import extract_items, to_raw_record
from hfr_scraper.validate import (
    clean_name,
    clean_pincode,
    clean_specialities,
    merge,
    validate,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _items():
    return extract_items(json.loads((FIXTURES / "search_page_synthetic.json").read_text(encoding="utf-8")))


def records():
    """First occurrence of each id (IN3200000001 appears twice in the fixture)."""
    out = {}
    for item in _items():
        out.setdefault(item["facilityId"], to_raw_record(item))
    return out


def duplicate_of_first():
    """The second, sparser IN3200000001 record: same facility under another district."""
    return to_raw_record([i for i in _items() if i["facilityId"] == "IN3200000001"][1])


def test_clean_record_is_normalised():
    f, reasons = validate(records()["IN3200000001"])
    assert reasons == []
    assert f.state_code == "32" and f.district_code == "590"
    assert f.latitude == Decimal("8.885000")
    assert f.has_icu is True and f.abdm_software is True
    assert (f.total_beds, f.icu_beds) == (50, 8)


def test_messy_record_is_cleaned_not_rejected():
    f, reasons = validate(records()["IN3200000002"])
    assert reasons == []
    assert f.name == "Sample City Clinic"            # whitespace collapsed, caps fixed
    assert f.pincode == "691001"                     # "691 001" -> digits
    assert f.latitude is None and f.longitude is None  # (0, 0) means unknown
    assert f.specialities == ["General Medicine", "Ayush"]  # comma string, de-duplicated


@pytest.mark.parametrize(
    "fid, reason",
    [
        ("IN3200000003", "invalid_pincode"),
        ("IN3200000004", "icu_beds_exceed_total"),
        ("IN3200000005", "latitude_out_of_range"),
        ("IN3200000006", "missing_district"),
        ("IN0300000007", "state_code_mismatch"),
        ("BADID", "invalid_facility_id"),
    ],
)
def test_bad_records_are_rejected_with_a_reason(fid, reason):
    f, reasons = validate(records()[fid])
    assert f is None
    assert reason in reasons


def test_state_code_is_taken_from_facility_id_when_missing():
    raw = {"facility_id": "IN0310000334", "name": "Punjab Clinic", "district_code": "10"}
    f, reasons = validate(raw)
    assert reasons == [] and f.state_code == "03"


def test_ownership_code_is_derived_when_site_gives_only_a_name():
    f, _ = validate({"facility_id": "IN3200000001", "name": "A", "district_code": "1", "ownership": "Private"})
    assert f.ownership_code == "PRIVATE"


@pytest.mark.parametrize("value, expected", [("110001", ("110001", True)), (" 110 001 ", ("110001", True)),
                                             (None, (None, True)), ("1100011", (None, False)), ("abc", (None, False))])
def test_clean_pincode(value, expected):
    assert clean_pincode(value) == expected


def test_clean_name_and_specialities():
    assert clean_name("  CITY   HOSPITAL ") == "City Hospital"
    assert clean_name("AIIMS Delhi") == "AIIMS Delhi"  # mixed case left alone
    assert clean_specialities([{"name": "ENT"}, "ent", " Cardiology "]) == ["ENT", "Cardiology"]


def test_merge_prefers_newer_values_but_keeps_old_ones_and_unions_specialities():
    first, _ = validate(records()["IN3200000001"])
    second, _ = validate(duplicate_of_first())  # no beds, no coordinates, one new speciality
    second.address = "New address"
    merged = merge(first, second)
    assert merged.latitude == Decimal("8.885000")       # old value kept
    assert merged.total_beds == 50                      # old value kept
    assert merged.address == "New address"              # newer value wins
    assert merged.specialities == ["Cardiology", "Paediatrics", "Orthopaedics"]
    assert merged.has_icu is True
