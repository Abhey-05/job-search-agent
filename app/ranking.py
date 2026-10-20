"""Configurable job ranking.

Pure function of (job row, preferences config) -> (score, explanation).
No I/O, no side effects -- easy to unit test and easy for the user to
retune by editing preferences.ranking_weights in config.yaml.
"""
from __future__ import annotations

from datetime import datetime, timezone

DEFAULT_WEIGHTS = {
    "title_match": 0.35,
    "company_match": 0.20,
    "location_match": 0.15,
    "keyword_boost": 0.15,
    "recency": 0.15,
}


def _tokenize(text: str) -> set[str]:
    return {t for t in "".join(c if c.isalnum() else " " for c in text.lower()).split() if t}


def _title_match_score(job_title: str, target_roles: list[str]) -> float:
    if not target_roles:
        return 0.5
    job_tokens = _tokenize(job_title)
    best = 0.0
    for role in target_roles:
        role_tokens = _tokenize(role)
        if not role_tokens:
            continue
        overlap = len(job_tokens & role_tokens) / len(role_tokens)
        best = max(best, overlap)
    return min(best, 1.0)


def _company_match_score(company: str, target_companies: list[str]) -> float:
    if not target_companies:
        return 0.5  # neutral when no preference configured
    norm_targets = {t.lower().strip() for t in target_companies}
    return 1.0 if company.lower().strip() in norm_targets else 0.0


def _location_match_score(location: str, locations: list[str], remote_ok: bool) -> float:
    if not locations:
        return 0.5
    loc_lower = (location or "").lower()
    if remote_ok and "remote" in loc_lower:
        return 1.0
    for pref in locations:
        if pref.lower().strip() in loc_lower:
            return 1.0
    return 0.2


def _keyword_score(title: str, description: str, boost: list[str], exclude: list[str]) -> float:
    text = f"{title} {description}".lower()
    if any(bad.lower() in text for bad in exclude or []):
        return -1.0  # hard penalty, surfaced in explanation
    if not boost:
        return 0.5
    hits = sum(1 for kw in boost if kw.lower() in text)
    return min(hits / max(len(boost), 1), 1.0)


def _recency_score(posted_at: str | None) -> float:
    if not posted_at:
        return 0.5
    try:
        posted = datetime.fromisoformat(posted_at)
    except ValueError:
        return 0.5
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - posted).days
    if age_days <= 1:
        return 1.0
    if age_days <= 7:
        return 0.8
    if age_days <= 14:
        return 0.5
    if age_days <= 30:
        return 0.25
    return 0.1


def rank_job(job_row, preferences: dict) -> tuple[float, list[str]]:
    weights = {**DEFAULT_WEIGHTS, **(preferences.get("ranking_weights") or {})}
    explanation = []

    title_s = _title_match_score(job_row["title"], preferences.get("target_roles", []))
    explanation.append(f"title_match={title_s:.2f} (weight {weights['title_match']})")

    company_s = _company_match_score(job_row["company"], preferences.get("target_companies", []))
    explanation.append(f"company_match={company_s:.2f} (weight {weights['company_match']})")

    location_s = _location_match_score(
        job_row["location"], preferences.get("locations", []), preferences.get("remote_ok", True)
    )
    explanation.append(f"location_match={location_s:.2f} (weight {weights['location_match']})")

    keyword_s = _keyword_score(
        job_row["title"], job_row["description"] or "",
        preferences.get("keywords_boost", []), preferences.get("keywords_exclude", []),
    )
    if keyword_s < 0:
        explanation.append("keyword_boost=EXCLUDED (matched an excluded keyword)")
    else:
        explanation.append(f"keyword_boost={keyword_s:.2f} (weight {weights['keyword_boost']})")

    recency_s = _recency_score(job_row["posted_at"])
    explanation.append(f"recency={recency_s:.2f} (weight {weights['recency']})")

    if keyword_s < 0:
        return 0.0, explanation

    score = (
        title_s * weights["title_match"]
        + company_s * weights["company_match"]
        + location_s * weights["location_match"]
        + keyword_s * weights["keyword_boost"]
        + recency_s * weights["recency"]
    )
    explanation.append(f"total={score:.3f}")
    return round(score, 4), explanation
