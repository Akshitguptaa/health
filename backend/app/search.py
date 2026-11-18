"""Builds the SQL for GET /api/facilities. Pure functions: no database access,
so the logic is unit-tested without Postgres."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MAX_PAGE_SIZE = 50
DEFAULT_PAGE_SIZE = 10

SELECT_FIELDS = """
    f.facility_id, f.name, f.status,
    o.code  AS ownership_code,  o.name  AS ownership,
    ft.code AS facility_type_code, ft.name AS facility_type,
    som.code AS som_code, som.name AS system_of_medicine,
    s.code  AS state_code, s.name AS state_name,
    d.lgd_code AS district_code, d.name AS district_name,
    sd.lgd_code AS sub_district_code, sd.name AS sub_district_name,
    f.village_city_town, f.address, f.pincode,
    f.latitude, f.longitude, f.abdm_software, f.photo_url,
    COALESCE(i.has_icu, FALSE) AS has_icu, i.total_beds, i.icu_beds
"""

FROM_CLAUSE = """
    FROM facilities f
    JOIN states s    ON s.code = f.state_code
    JOIN districts d ON d.id = f.district_id
    LEFT JOIN sub_districts sd        ON sd.id = f.sub_district_id
    LEFT JOIN ownership_types o       ON o.code = f.ownership_code
    LEFT JOIN facility_types ft       ON ft.code = f.facility_type_code
    LEFT JOIN systems_of_medicine som ON som.code = f.system_of_medicine_code
    LEFT JOIN facility_infrastructure i ON i.facility_id = f.facility_id
"""

SORTS = {
    "name": "f.name ASC",
    "district": "d.name ASC, f.name ASC",
    "beds": "i.total_beds DESC NULLS LAST, f.name ASC",
}


@dataclass
class SearchParams:
    state: str | None = None
    district: str | None = None
    subDistrict: str | None = None
    pincode: str | None = None
    name: str | None = None
    facilityId: str | None = None
    ownership: str | None = None
    facilityType: str | None = None
    systemOfMedicine: str | None = None
    speciality: str | None = None
    icu: str | None = None  # "yes" | "no"
    status: str | None = None
    sort: str | None = None
    page: int = 1
    pageSize: int = DEFAULT_PAGE_SIZE

    def filter_names(self) -> list[str]:
        """Names of the filters that were actually supplied."""
        skip = {"sort", "page", "pageSize"}
        return [k for k, v in self.__dict__.items() if k not in skip and v not in (None, "")]


@dataclass
class BuiltQuery:
    where: str
    args: list[Any] = field(default_factory=list)
    order_by: str = SORTS["name"]
    order_args: list[Any] = field(default_factory=list)


def build_query(p: SearchParams) -> BuiltQuery:
    # facilityId is an exact lookup: every other filter is ignored.
    if p.facilityId:
        return BuiltQuery(where="f.facility_id = %s", args=[p.facilityId.upper()])

    clauses: list[str] = []
    args: list[Any] = []

    def eq(column: str, value: Any) -> None:
        clauses.append(f"{column} = %s")
        args.append(value)

    if p.state:
        eq("f.state_code", p.state)
    if p.district:
        eq("d.lgd_code", p.district)
    if p.subDistrict:
        eq("sd.lgd_code", p.subDistrict)
    if p.pincode:
        eq("f.pincode", p.pincode)
    if p.ownership:
        eq("f.ownership_code", p.ownership.upper())
    if p.facilityType:
        eq("f.facility_type_code", p.facilityType.upper())
    if p.systemOfMedicine:
        eq("f.system_of_medicine_code", p.systemOfMedicine.upper())
    if p.status:
        clauses.append("lower(f.status) = lower(%s)")
        args.append(p.status)
    if p.icu:
        clauses.append("COALESCE(i.has_icu, FALSE) = %s")
        args.append(p.icu.lower() == "yes")
    if p.speciality:
        clauses.append(
            "EXISTS (SELECT 1 FROM facility_specialities fs"
            " JOIN specialities sp ON sp.id = fs.speciality_id"
            " WHERE fs.facility_id = f.facility_id AND lower(sp.name) = lower(%s))"
        )
        args.append(p.speciality)

    order_by = SORTS.get(p.sort or "", SORTS["name"])
    order_args: list[Any] = []
    if p.name:
        term = p.name.strip().lower()
        # Substring match OR word-similarity (typo tolerant). Both use the
        # trigram GIN index on lower(name); the threshold is set per connection.
        clauses.append("(lower(f.name) LIKE %s OR %s <%% lower(f.name))")
        args += [f"%{_escape_like(term)}%", term]
        if not p.sort:
            order_by = "word_similarity(%s, lower(f.name)) DESC, f.name ASC"
            order_args.append(term)

    return BuiltQuery(
        where=" AND ".join(clauses) if clauses else "TRUE",
        args=args,
        order_by=order_by,
        order_args=order_args,
    )


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def count_sql(q: BuiltQuery) -> tuple[str, list[Any]]:
    return f"SELECT count(*) AS n {FROM_CLAUSE} WHERE {q.where}", list(q.args)


def page_sql(q: BuiltQuery, page: int, page_size: int) -> tuple[str, list[Any]]:
    sql = (
        f"SELECT {SELECT_FIELDS} {FROM_CLAUSE} WHERE {q.where} "
        f"ORDER BY {q.order_by}, f.facility_id ASC LIMIT %s OFFSET %s"
    )
    return sql, [*q.args, *q.order_args, page_size, (page - 1) * page_size]


def number_of_pages(total: int, page_size: int) -> int:
    return (total + page_size - 1) // page_size
