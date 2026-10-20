"""Builds a LinkedIn Jobs search URL from filter selections.

This does exactly one thing: constructs a URL using LinkedIn's own public
jobs-search page and its documented query parameters -- the same page and
same parameters you'd land on by typing a keyword and clicking LinkedIn's
own filter chips in a browser. It never requests, fetches, or parses
anything from LinkedIn itself; the user opens the resulting link in their
own browser, logged into their own account, and LinkedIn's own interface
does the rest.

No scraping, no authentication, no automation of LinkedIn's logged-in
interface happens here or anywhere else in this app. If LinkedIn changes
these parameter names (they are not a stable public API, just the current
behavior of their search page), the generated link will still open their
search page -- it may just land on an unfiltered or differently-filtered
result, which the user can then adjust manually.
"""
from __future__ import annotations

from urllib.parse import urlencode

BASE_URL = "https://www.linkedin.com/jobs/search/"

DATE_POSTED_OPTIONS = {
    "any": None,
    "past_month": "r2592000",
    "past_week": "r604800",
    "past_24h": "r86400",
}

EXPERIENCE_LEVEL_OPTIONS = {
    "internship": "1",
    "entry_level": "2",
    "associate": "3",
    "mid_senior": "4",
    "director": "5",
    "executive": "6",
}

EMPLOYMENT_TYPE_OPTIONS = {
    "full_time": "F",
    "part_time": "P",
    "contract": "C",
    "temporary": "T",
    "internship": "I",
    "volunteer": "V",
}

WORKPLACE_TYPE_OPTIONS = {
    "on_site": "1",
    "remote": "2",
    "hybrid": "3",
}


def build_linkedin_search_url(
    keywords: str,
    location: str = "",
    date_posted: str = "any",
    experience_levels: list[str] | None = None,
    employment_types: list[str] | None = None,
    workplace_types: list[str] | None = None,
    easy_apply: bool = False,
) -> str:
    params: dict[str, str] = {}
    if keywords:
        params["keywords"] = keywords
    if location:
        params["location"] = location

    tpr = DATE_POSTED_OPTIONS.get(date_posted)
    if tpr:
        params["f_TPR"] = tpr

    if experience_levels:
        codes = [EXPERIENCE_LEVEL_OPTIONS[e] for e in experience_levels if e in EXPERIENCE_LEVEL_OPTIONS]
        if codes:
            params["f_E"] = ",".join(codes)

    if employment_types:
        codes = [EMPLOYMENT_TYPE_OPTIONS[e] for e in employment_types if e in EMPLOYMENT_TYPE_OPTIONS]
        if codes:
            params["f_JT"] = ",".join(codes)

    if workplace_types:
        codes = [WORKPLACE_TYPE_OPTIONS[w] for w in workplace_types if w in WORKPLACE_TYPE_OPTIONS]
        if codes:
            params["f_WT"] = ",".join(codes)

    if easy_apply:
        params["f_AL"] = "true"

    return f"{BASE_URL}?{urlencode(params)}"


def build_keywords_with_company(keywords: str, company: str) -> str:
    """LinkedIn's company filter (f_C) needs a numeric LinkedIn company ID,
    which isn't resolvable without LinkedIn API/scraping access. As a
    practical substitute, fold the company name into the keyword string --
    LinkedIn's own search still matches on it, just as a text term rather
    than a strict filter chip."""
    if not company:
        return keywords
    return f"{keywords} {company}".strip()
