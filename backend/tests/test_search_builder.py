from app.search import (
    MAX_PAGE_SIZE,
    SearchParams,
    build_query,
    count_sql,
    number_of_pages,
    page_sql,
)


def test_filter_names_ignores_paging_and_sort():
    p = SearchParams(sort="name", page=3, pageSize=20)
    assert p.filter_names() == []
    assert SearchParams(state="32", name="heart").filter_names() == ["state", "name"]


def test_facility_id_overrides_every_other_filter():
    q = build_query(SearchParams(facilityId="in3200004821", state="32", name="heart", icu="yes"))
    assert q.where == "f.facility_id = %s"
    assert q.args == ["IN3200004821"]


def test_exact_filters_use_bound_parameters_not_string_building():
    q = build_query(SearchParams(state="32", district="590", pincode="691001", ownership="p"))
    assert q.where == "f.state_code = %s AND d.lgd_code = %s AND f.pincode = %s AND f.ownership_code = %s"
    assert q.args == ["32", "590", "691001", "P"]


def test_name_search_is_partial_and_typo_tolerant_and_escaped():
    q = build_query(SearchParams(name="  Hea_rt% "))
    assert "LIKE %s" in q.where and "<% lower(f.name)" in q.where.replace("<%%", "<%")
    assert q.args[0] == "%hea\\_rt\\%%"  # wildcard characters typed by the user are escaped
    assert q.args[1] == "hea_rt%"


def test_name_search_ranks_by_similarity_unless_sort_given():
    ranked = build_query(SearchParams(name="heart"))
    assert ranked.order_by.startswith("word_similarity")
    assert ranked.order_args == ["heart"]
    explicit = build_query(SearchParams(name="heart", sort="beds"))
    assert explicit.order_by.startswith("i.total_beds DESC")
    assert explicit.order_args == []


def test_icu_filter_maps_yes_no_to_boolean():
    assert build_query(SearchParams(icu="Yes")).args == [True]
    assert build_query(SearchParams(icu="no")).args == [False]


def test_speciality_filter_uses_exists_subquery():
    q = build_query(SearchParams(speciality="Cardiology"))
    assert "EXISTS (SELECT 1 FROM facility_specialities" in q.where
    assert q.args == ["Cardiology"]


def test_page_sql_offset_and_stable_tiebreak():
    q = build_query(SearchParams(state="32"))
    sql, args = page_sql(q, page=3, page_size=10)
    assert args == ["32", 10, 20]
    assert sql.strip().endswith("LIMIT %s OFFSET %s")
    assert "f.facility_id ASC" in sql  # stable pagination


def test_page_args_keep_placeholder_order_with_name_ranking():
    q = build_query(SearchParams(name="heart", state="32"))
    _, args = page_sql(q, page=2, page_size=5)
    # where args..., then ORDER BY arg, then LIMIT/OFFSET
    assert args == ["32", "%heart%", "heart", "heart", 5, 5]


def test_count_sql_has_no_order_or_paging():
    sql, args = count_sql(build_query(SearchParams(state="32", name="heart")))
    assert "ORDER BY" not in sql and "LIMIT" not in sql
    assert args == ["32", "%heart%", "heart"]


def test_number_of_pages():
    assert number_of_pages(0, 10) == 0
    assert number_of_pages(37, 10) == 4
    assert number_of_pages(100, MAX_PAGE_SIZE) == 2
