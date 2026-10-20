from app.linkedin_search import build_keywords_with_company, build_linkedin_search_url


def test_basic_url_has_keywords_and_base():
    url = build_linkedin_search_url(keywords="Product Manager")
    assert url.startswith("https://www.linkedin.com/jobs/search/?")
    assert "keywords=Product+Manager" in url


def test_filters_map_to_linkedin_codes():
    url = build_linkedin_search_url(
        keywords="Product Analyst",
        location="Bangalore",
        date_posted="past_week",
        experience_levels=["entry_level", "associate"],
        employment_types=["full_time"],
        workplace_types=["remote", "hybrid"],
        easy_apply=True,
    )
    assert "f_TPR=r604800" in url
    assert "f_E=2%2C3" in url  # entry_level=2, associate=3
    assert "f_JT=F" in url
    assert "f_WT=2%2C3" in url  # remote=2, hybrid=3
    assert "f_AL=true" in url


def test_unknown_filter_values_are_ignored_not_crashed():
    url = build_linkedin_search_url(keywords="PM", experience_levels=["not_a_real_level"])
    assert "f_E=" not in url


def test_company_is_folded_into_keywords():
    combined = build_keywords_with_company("Product Manager", "Navi")
    assert combined == "Product Manager Navi"
    assert build_keywords_with_company("Product Manager", "") == "Product Manager"
