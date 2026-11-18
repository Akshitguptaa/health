import json
from pathlib import Path

from hfr_scraper.parsers import extract_items, to_raw_record, total_pages

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_extracts_all_items_and_page_count_from_search_page():
    payload = load("search_page_synthetic.json")
    assert len(extract_items(payload)) == 9
    assert total_pages(payload) == 3


def test_extracts_single_facility_from_wrapped_detail_response():
    items = extract_items(load("facility_detail_synthetic.json"))
    assert len(items) == 1 and items[0]["facilityId"] == "IN3200000002"


def test_wrapper_key_variants_are_understood():
    assert extract_items({"content": [{"facilityId": "IN3200000001"}]}) == [{"facilityId": "IN3200000001"}]
    assert extract_items({"data": {"facilities": [{"facilityId": "IN3200000001"}]}})
    assert extract_items([{"facilityId": "IN3200000001"}, "junk"]) == [{"facilityId": "IN3200000001"}]


def test_capture_bundle_from_browser_helper_is_flattened():
    page = load("search_page_synthetic.json")
    detail = load("facility_detail_synthetic.json")
    bundle = {"captures": [page, page, detail]}
    assert len(extract_items(bundle)) == 9 + 9 + 1
    assert len(extract_items([page, detail])) == 9 + 1  # a plain list of pages works too


def test_unknown_payloads_yield_nothing_instead_of_crashing():
    assert extract_items({"message": "no results"}) == []
    assert extract_items("<html>captcha</html>") == []
    assert extract_items(None) == []


def test_total_pages_accepts_numeric_strings_and_missing():
    assert total_pages({"totalPages": "7"}) == 7
    assert total_pages({"data": {"numberOfPages": 2}}) == 2
    assert total_pages({}) is None


def test_to_raw_record_maps_aliases_to_canonical_keys():
    raw = to_raw_record({"facilityID": "IN3200000001", "name": "X", "pinCode": "110001", "stateLgdCode": "32"})
    assert raw == {"facility_id": "IN3200000001", "name": "X", "pincode": "110001", "state_code": "32"}
