-- Core normalised schema: masters, facilities, specialities, infrastructure.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------- master tables ----------
CREATE TABLE states (
    code  CHAR(2) PRIMARY KEY CHECK (code ~ '^[0-9]{2}$'),   -- LGD state code
    name  TEXT NOT NULL UNIQUE
);

CREATE TABLE districts (
    id          SERIAL PRIMARY KEY,
    state_code  CHAR(2) NOT NULL REFERENCES states (code),
    lgd_code    TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    UNIQUE (state_code, lgd_code)
);

CREATE TABLE sub_districts (
    id           SERIAL PRIMARY KEY,
    district_id  INTEGER NOT NULL REFERENCES districts (id),
    lgd_code     TEXT    NOT NULL,
    name         TEXT    NOT NULL,
    UNIQUE (district_id, lgd_code)
);

CREATE TABLE ownership_types (
    code  TEXT PRIMARY KEY,          -- e.g. 'P'
    name  TEXT NOT NULL UNIQUE       -- e.g. 'Private'
);

CREATE TABLE facility_types (
    code  TEXT PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE       -- e.g. 'Hospital', 'Clinic'
);

CREATE TABLE systems_of_medicine (
    code  TEXT PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE       -- e.g. 'Modern Medicine', 'Ayurveda'
);

CREATE TABLE specialities (
    id    SERIAL PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE
);

-- ---------- facilities ----------
CREATE TABLE facilities (
    facility_id             CHAR(12) PRIMARY KEY
        CHECK (facility_id ~ '^IN[0-9]{10}$'),
    name                    TEXT    NOT NULL,
    status                  TEXT    NOT NULL DEFAULT 'Submitted',
    ownership_code          TEXT    REFERENCES ownership_types (code),
    facility_type_code      TEXT    REFERENCES facility_types (code),
    system_of_medicine_code TEXT    REFERENCES systems_of_medicine (code),
    state_code              CHAR(2) NOT NULL REFERENCES states (code),
    district_id             INTEGER NOT NULL REFERENCES districts (id),
    sub_district_id         INTEGER REFERENCES sub_districts (id),
    village_city_town       TEXT,
    address                 TEXT,
    pincode                 CHAR(6) CHECK (pincode ~ '^[0-9]{6}$'),
    latitude                NUMERIC(9, 6) CHECK (latitude  BETWEEN -90  AND 90),
    longitude               NUMERIC(9, 6) CHECK (longitude BETWEEN -180 AND 180),
    abdm_software           BOOLEAN NOT NULL DEFAULT FALSE,
    photo_url               TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- the 2-digit state code inside the ID must agree with the state column
    CONSTRAINT facility_id_matches_state CHECK (substr(facility_id, 3, 2) = state_code)
);

CREATE TABLE facility_specialities (
    facility_id    CHAR(12) NOT NULL REFERENCES facilities (facility_id) ON DELETE CASCADE,
    speciality_id  INTEGER  NOT NULL REFERENCES specialities (id),
    PRIMARY KEY (facility_id, speciality_id)
);

-- Beds are nullable: the public site does not publish them for every facility.
CREATE TABLE facility_infrastructure (
    facility_id  CHAR(12) PRIMARY KEY REFERENCES facilities (facility_id) ON DELETE CASCADE,
    total_beds   INTEGER CHECK (total_beds >= 0),
    icu_beds     INTEGER CHECK (icu_beds >= 0),
    has_icu      BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT icu_not_above_total
        CHECK (icu_beds IS NULL OR total_beds IS NULL OR icu_beds <= total_beds)
);
