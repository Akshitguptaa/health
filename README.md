# Health Facility Finder

NHPR facility search data → PostgreSQL → read-only API → search frontend.

## Status

| Requirement | State |
|---|---|
| Scraper, schema + migrations, API, frontend, tests | Done |
| 1,000+ facilities, 5+ states, 25+ districts | **Not met: 135 facilities, 1 state (Delhi), 13 districts** |

Why: NHPR needs a captcha for every results page, and nothing here solves or bypasses it. A person solves
the captchas; `scraper/browser/capture.js` (pasted in the browser console) saves the pages the browser
received, and `ingest` loads them.

## Architecture

```mermaid
flowchart LR
    H[Person solves captcha] --> C[capture.js] --> S[Scraper: ingest<br/>parse, clean, dedupe] --> DB[(PostgreSQL 16)] --> API[FastAPI] --> FE[Static frontend]
```

```mermaid
erDiagram
    states ||--o{ districts : has
    districts ||--o{ sub_districts : has
    districts ||--o{ facilities : in
    facilities ||--o| facility_infrastructure : has
    facilities ||--o{ facility_specialities : offers
    specialities ||--o{ facility_specialities : "offered by"
    ownership_types |o--o{ facilities : classifies
    facility_types |o--o{ facilities : classifies
    systems_of_medicine |o--o{ facilities : classifies
```

Also: `raw_responses`, `quarantine`, `crawl_progress`, `scrape_runs`. Constraints cover id format, state/id match,
pincode, coordinates, beds and ICU ≤ total. `pg_trgm` index on name.

## Run

```bash
DB_PORT=55432 docker compose up -d db
pip install -r requirements.txt
export DATABASE_URL=postgresql://hfr:hfr@127.0.0.1:55432/hfr
cd backend && python -m app.migrate
CORS_ORIGINS=http://localhost:8123 uvicorn app.main:app --port 8000   # docs at /docs
python scripts/serve_frontend.py 8123                                 # repo root, new terminal
```

Tests: `pytest` (DB tests need `DATABASE_URL`; `HFR_TEST_ALLOW_WIPE=1` adds a test that **empties the tables**, use a throwaway DB). Lint: `ruff check backend scraper scripts`.

## Load data

1. On the NHPR search page, paste `scraper/browser/capture.js` into the console, search, solve captchas, run `hfrSave()`.
2. Put the files in `data/raw/` (git-ignored) and run `cd scraper && python -m hfr_scraper ingest ../data/raw`.

Each run prints a report (pages, loaded, duplicates, rejects by reason). A `crawl` command exists but was never run against the live site.

**Data rules:** raw pages are stored with personal contact details and photos removed; invalid records go to `quarantine` with a reason; the facility id is the identity (newer non-empty values win, specialities merged); all writes are idempotent upserts and finished files are skipped.

## API

`GET /api/facilities` (filters: state, district, subDistrict, pincode, name, facilityId, ownership, facilityType, systemOfMedicine, speciality, icu, status; sort, page, pageSize ≤ 50; at least one filter; 60 req/min/IP), `/api/facilities/{id}`, `/api/masters/...`, `/api/stats`, `/health`. Errors: `{"error": {"code", "message", "details"}}`.

## Frontend

Vanilla JS in `frontend/`: search filters, results, pagination, details page, stats page. Search state lives in the URL.

## Known issues

- Delhi only; other states may fill fields differently.
- ICU bed counts are empty in all data seen, so the ICU filter under-reports.
- District codes are NHPR ids, not LGD codes.

## AI tools used

Claude Code wrote most of the code, tests and this README from the brief.
