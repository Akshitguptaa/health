"""Parsing the real NHPR record shape (synthetic values, real field names)."""
import json
from decimal import Decimal
from pathlib import Path

from hfr_scraper.parsers import extract_items, from_nhpr_record, sanitize, to_raw_record, total_pages
from hfr_scraper.validate import merge, validate

FIXTURE = Path(__file__).parent / "fixtures" / "capture_bundle_nhpr_shape.json"


def bundle():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def items():
    return extract_items(bundle())


def by_id(fid):
    return [i for i in items() if i["alternateId"] == fid][0]


def test_spring_page_wrapper_and_bundle_are_understood():
    assert len(items()) == 5                      # 4 on page 1 + 1 duplicate on page 2
    assert total_pages(bundle()["captures"][0]) == 2


def test_maps_the_real_field_names():
    raw = to_raw_record(by_id("IN0700000001"))
    assert raw["facility_id"] == "IN0700000001"
    assert raw["name"] == "Example Hospital One"
    assert (raw["state_code"], raw["state_name"]) == ("07", "Testland")
    assert (raw["district_code"], raw["district_name"].strip()) == ("79", "New Delhi")
    assert raw["address"] == "1 Example Road, Block B"
    assert raw["ownership"] == "Private" and raw["ownership_code"] == "P"
    # multi-valued systems of medicine are sorted so the same set always gives the same value
    assert raw["system_of_medicine"] == "Dentistry, Modern Medicine(Allopathy), Physiotherapy"
    assert raw["total_beds"] == "50" and raw["has_icu"] == "Yes"
    assert (raw["latitude"], raw["longitude"]) == ("28.528922", "77.2437530000001")


def test_only_active_specialities_are_kept_and_names_are_trimmed():
    raw = from_nhpr_record(by_id("IN0700000001"))
    assert raw["specialities"] == ["Cardiology", "General Medicine"]


def test_real_record_validates_and_coordinates_are_rounded():
    f, reasons = validate(to_raw_record(by_id("IN0700000001")))
    assert reasons == []
    assert f.latitude == Decimal("28.528922") and f.longitude == Decimal("77.243753")
    assert f.total_beds == 50 and f.has_icu is True and f.abdm_software is True
    assert f.district_name == "New Delhi"          # padding removed


def test_facility_without_infrastructure_or_specialities_is_still_valid():
    f, reasons = validate(to_raw_record(by_id("IN0700000002")))
    assert reasons == []
    assert f.ownership == "Government" and f.total_beds is None and f.specialities == []
    assert f.has_icu is False and f.abdm_software is False


def test_malformed_geolocation_is_rejected_not_dropped():
    f, reasons = validate(to_raw_record(by_id("IN0700000003")))
    assert f is None and "invalid_coordinates" in reasons


def test_empty_geolocation_means_unknown_location():
    f, reasons = validate(to_raw_record(by_id("IN0700000004")))
    assert reasons == [] and f.latitude is None
    assert f.ownership is None and f.ownership_code == "X"   # unknown code kept, name not invented


def test_the_same_facility_on_two_pages_is_merged():
    page1, page2 = [to_raw_record(i) for i in items() if i["alternateId"] == "IN0700000001"]
    a, _ = validate(page1)
    b, _ = validate(page2)
    merged = merge(a, b)
    assert merged.total_beds == 50                              # kept from the fuller record
    assert merged.specialities == ["Cardiology", "General Medicine", "Paediatrics"]


def test_sanitize_removes_personal_details_user_ids_and_photos():
    clean = sanitize(bundle())
    text = json.dumps(clean)
    for secret in ("Test Person", "example.invalid", "0000000000", "00-0000-0000-0000", "QUJD"):
        assert secret not in text, secret
    record = clean["captures"][0]["content"][0]
    assert "buildImage" not in record and "facContactPerName" not in record
    assert record["facName"] == "Example Hospital One"          # useful fields survive
    assert record["specialityDtls"][0]["specName"].strip() == "Cardiology"


def test_sanitize_does_not_change_the_input():
    data = bundle()
    sanitize(data)
    assert "facContactPerName" in data["captures"][0]["content"][0]
