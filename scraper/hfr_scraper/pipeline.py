"""Glue: payload -> raw capture -> parse -> validate -> dedupe -> database."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .parsers import extract_items, sanitize, to_raw_record
from .report import RunStats
from .store import Store
from .validate import Facility, merge, validate


class Loader:
    """Holds the in-run dedupe map so a facility seen under two districts is merged."""

    def __init__(self, store: Store, stats: RunStats) -> None:
        self.store = store
        self.stats = stats
        self.seen: dict[str, Facility] = {}

    def load_payload(self, kind: str, source_key: str, payload: Any) -> int:
        """Process one fetched page/detail. Returns the number of facilities in it."""
        # Raw first, so parser bugs are fixable without re-crawling. Personal contact
        # details and embedded photos are removed before anything is stored.
        self.store.save_raw(kind, source_key, sanitize(payload))
        items = extract_items(payload)
        for item in items:
            self.stats.facilities_seen += 1
            facility, reasons = validate(to_raw_record(item))
            if reasons:
                fid = str(item.get("alternateId") or item.get("facilityId") or item.get("facilityID") or "") or None
                for reason in reasons:
                    self.stats.rejected[reason] += 1
                    self.store.quarantine(fid, reason, sanitize(item))
                continue
            assert facility is not None
            previous = self.seen.get(facility.facility_id)
            if previous is not None:
                self.stats.duplicates_merged += 1
                facility = merge(previous, facility)
            else:
                self.stats.facilities_loaded += 1
            self.seen[facility.facility_id] = facility
            self.store.upsert_facility(facility)
        self.stats.pages_processed += 1
        return len(items)


def ingest_path(store: Store, loader: Loader, path: Path, force: bool = False) -> None:
    """Load saved JSON captures (one file or a folder). Already-loaded files are skipped."""
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    for file in files:
        data = file.read_bytes()
        unit = f"file:{file.name}:{hashlib.sha256(data).hexdigest()[:16]}"
        if not force and store.is_done(unit):
            loader.stats.pages_skipped += 1
            continue
        payload = json.loads(data)
        # A capture bundle holds many result pages; keep each page as its own raw row.
        is_bundle = isinstance(payload, dict) and isinstance(payload.get("captures"), list)
        pages = payload["captures"] if is_bundle else [payload]
        for number, page in enumerate(pages, start=1):
            loader.load_payload("search_page", f"{file.name}#{number}", page)
        store.mark_done(unit)
        store.conn.commit()  # per file: an interrupted ingest keeps finished files
