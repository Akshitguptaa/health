-- Tables the scraper uses: raw capture, quarantine, progress, run summaries.

-- Raw JSON exactly as fetched, so parsing bugs can be fixed without re-crawling.
CREATE TABLE raw_responses (
    id          BIGSERIAL PRIMARY KEY,
    kind        TEXT        NOT NULL,           -- 'search_page' | 'facility_detail'
    source_key  TEXT        NOT NULL,           -- e.g. '03:101:page=2' or a facility id
    body        JSONB       NOT NULL,
    body_sha256 CHAR(64)    NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (kind, source_key, body_sha256)      -- same payload twice = one row
);

-- Records that failed validation. Never dropped silently.
CREATE TABLE quarantine (
    id          BIGSERIAL PRIMARY KEY,
    facility_id TEXT,
    reason      TEXT        NOT NULL,
    record      JSONB       NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (facility_id, reason)                -- reruns do not duplicate rows
);

-- Which (state, district, page) units are finished, so a rerun resumes.
CREATE TABLE crawl_progress (
    unit_key    TEXT PRIMARY KEY,               -- '03:101:page=2'
    status      TEXT        NOT NULL DEFAULT 'done',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE scrape_runs (
    id           BIGSERIAL PRIMARY KEY,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    stats        JSONB
);
