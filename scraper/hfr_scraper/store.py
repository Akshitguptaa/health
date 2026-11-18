"""All database writes for the scraper. Every write is an upsert, so running
the same input twice leaves the database in the same state."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .validate import Facility


def sha256_of(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class Store:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    # ----- raw capture, progress, quarantine, runs -----
    def save_raw(self, kind: str, source_key: str, payload: Any) -> None:
        self.conn.execute(
            "INSERT INTO raw_responses (kind, source_key, body, body_sha256) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (kind, source_key, body_sha256) DO NOTHING",
            (kind, source_key, Jsonb(payload), sha256_of(payload)),
        )

    def is_done(self, unit_key: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM crawl_progress WHERE unit_key = %s", (unit_key,)
        ).fetchone() is not None

    def mark_done(self, unit_key: str) -> None:
        self.conn.execute(
            "INSERT INTO crawl_progress (unit_key) VALUES (%s)"
            " ON CONFLICT (unit_key) DO UPDATE SET updated_at = now()",
            (unit_key,),
        )

    def quarantine(self, facility_id: str | None, reason: str, record: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO quarantine (facility_id, reason, record) VALUES (%s, %s, %s)"
            " ON CONFLICT (facility_id, reason) DO UPDATE SET record = EXCLUDED.record",
            (facility_id, reason, Jsonb(record, dumps=lambda o: json.dumps(o, default=str))),
        )

    def start_run(self) -> int:
        return self.conn.execute("INSERT INTO scrape_runs DEFAULT VALUES RETURNING id").fetchone()[0]

    def finish_run(self, run_id: int, stats: dict[str, Any]) -> None:
        self.conn.execute(
            "UPDATE scrape_runs SET finished_at = now(), stats = %s WHERE id = %s",
            (Jsonb(stats), run_id),
        )

    # ----- facilities -----
    def upsert_facility(self, f: Facility) -> None:
        c = self.conn
        c.execute(
            "INSERT INTO states (code, name) VALUES (%s, %s)"
            " ON CONFLICT (code) DO UPDATE SET name = COALESCE(EXCLUDED.name, states.name)",
            (f.state_code, f.state_name or f"State {f.state_code}"),
        )
        district_id = c.execute(
            "INSERT INTO districts (state_code, lgd_code, name) VALUES (%s, %s, %s)"
            " ON CONFLICT (state_code, lgd_code) DO UPDATE SET name = EXCLUDED.name RETURNING id",
            (f.state_code, f.district_code, f.district_name or f"District {f.district_code}"),
        ).fetchone()[0]
        sub_id = None
        if f.sub_district_code:
            sub_id = c.execute(
                "INSERT INTO sub_districts (district_id, lgd_code, name) VALUES (%s, %s, %s)"
                " ON CONFLICT (district_id, lgd_code) DO UPDATE SET name = EXCLUDED.name RETURNING id",
                (district_id, f.sub_district_code, f.sub_district_name or f"Sub-district {f.sub_district_code}"),
            ).fetchone()[0]
        # A master row is identified by its name first, so one name never gets two codes.
        ownership_code = self._master("ownership_types", f.ownership_code, f.ownership)
        type_code = self._master("facility_types", f.facility_type_code, f.facility_type)
        som_code = self._master("systems_of_medicine", f.som_code, f.system_of_medicine)

        c.execute(
            """
            INSERT INTO facilities (facility_id, name, status, ownership_code, facility_type_code,
                system_of_medicine_code, state_code, district_id, sub_district_id, village_city_town,
                address, pincode, latitude, longitude, abdm_software, photo_url)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (facility_id) DO UPDATE SET
                name = EXCLUDED.name,
                status = EXCLUDED.status,
                ownership_code = COALESCE(EXCLUDED.ownership_code, facilities.ownership_code),
                facility_type_code = COALESCE(EXCLUDED.facility_type_code, facilities.facility_type_code),
                system_of_medicine_code = COALESCE(
                    EXCLUDED.system_of_medicine_code, facilities.system_of_medicine_code),
                state_code = EXCLUDED.state_code,
                district_id = EXCLUDED.district_id,
                sub_district_id = COALESCE(EXCLUDED.sub_district_id, facilities.sub_district_id),
                village_city_town = COALESCE(EXCLUDED.village_city_town, facilities.village_city_town),
                address = COALESCE(EXCLUDED.address, facilities.address),
                pincode = COALESCE(EXCLUDED.pincode, facilities.pincode),
                latitude = COALESCE(EXCLUDED.latitude, facilities.latitude),
                longitude = COALESCE(EXCLUDED.longitude, facilities.longitude),
                abdm_software = EXCLUDED.abdm_software OR facilities.abdm_software,
                photo_url = COALESCE(EXCLUDED.photo_url, facilities.photo_url),
                updated_at = now()
            """,
            (
                f.facility_id, f.name, f.status, ownership_code, type_code, som_code,
                f.state_code, district_id, sub_id, f.village_city_town, f.address, f.pincode,
                f.latitude, f.longitude, f.abdm_software, f.photo_url,
            ),
        )
        c.execute(
            "INSERT INTO facility_infrastructure (facility_id, total_beds, icu_beds, has_icu)"
            " VALUES (%s,%s,%s,%s)"
            " ON CONFLICT (facility_id) DO UPDATE SET"
            "  total_beds = COALESCE(EXCLUDED.total_beds, facility_infrastructure.total_beds),"
            "  icu_beds = COALESCE(EXCLUDED.icu_beds, facility_infrastructure.icu_beds),"
            "  has_icu = EXCLUDED.has_icu OR facility_infrastructure.has_icu",
            (f.facility_id, f.total_beds, f.icu_beds, f.has_icu),
        )
        for name in f.specialities:
            spec_id = c.execute(
                "INSERT INTO specialities (name) VALUES (%s)"
                " ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
                (name,),
            ).fetchone()[0]
            c.execute(
                "INSERT INTO facility_specialities (facility_id, speciality_id) VALUES (%s, %s)"
                " ON CONFLICT DO NOTHING",
                (f.facility_id, spec_id),
            )

    def _master(self, table: str, code: str | None, name: str | None) -> str | None:
        """Ensure a master row exists and return the code the facility should use."""
        if not code:
            return None
        if table not in {"ownership_types", "facility_types", "systems_of_medicine"}:
            raise ValueError(table)  # table names are never user-supplied
        if name:
            existing = self.conn.execute(f"SELECT code FROM {table} WHERE name = %s", (name,)).fetchone()
            if existing:
                return existing[0]
        self.conn.execute(
            f"INSERT INTO {table} (code, name) VALUES (%s, %s)"
            " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name",
            (code, name or code),
        )
        return code
