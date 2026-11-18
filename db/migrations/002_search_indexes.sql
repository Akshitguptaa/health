-- Indexes that back GET /api/facilities.

-- Partial, typo-tolerant name search (ILIKE '%foo%' and similarity()).
CREATE INDEX facilities_name_trgm_idx
    ON facilities USING gin (lower(name) gin_trgm_ops);

CREATE INDEX facilities_state_idx        ON facilities (state_code);
CREATE INDEX facilities_district_idx     ON facilities (district_id);
CREATE INDEX facilities_sub_district_idx ON facilities (sub_district_id);
CREATE INDEX facilities_pincode_idx      ON facilities (pincode);
CREATE INDEX facilities_ownership_idx    ON facilities (ownership_code);
CREATE INDEX facilities_type_idx         ON facilities (facility_type_code);
CREATE INDEX facilities_system_idx       ON facilities (system_of_medicine_code);
CREATE INDEX facilities_status_idx       ON facilities (status);

-- Lookup facilities by speciality (the PK already covers facility -> speciality).
CREATE INDEX facility_specialities_speciality_idx
    ON facility_specialities (speciality_id);

CREATE INDEX infrastructure_has_icu_idx ON facility_infrastructure (has_icu);

CREATE INDEX districts_state_idx ON districts (state_code);
