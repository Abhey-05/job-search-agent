"""Application package preparation.

Deterministic, template-based tailoring: takes the user's uploaded resume
text (app/resume_store.py) and layers in which configured skills/boosted
keywords actually appear in the job description, plus a job-specific
header. No external LLM call is made here -- see docs/INTEGRATIONS.md for
how to wire in real AI-assisted tailoring later.

Output is returned as plain text/markdown strings, not written to disk --
the pipeline stores them directly in the `applications` table so the
content survives redeploys and is visible from the dashboard regardless of
which process (web or worker) generated it.
"""
from __future__ import annotations

from app.resume_store import get_current_resume_text


def _matched_keywords(job_row, preferences: dict) -> list[str]:
    text = f"{job_row['title']} {job_row['description'] or ''}".lower()
    skills = preferences.get("keywords_boost", []) or []
    return [kw for kw in skills if kw.lower() in text]


def prepare_application_package(job_row, config, db) -> dict:
    base_resume = get_current_resume_text(db)
    matched = _matched_keywords(job_row, config.preferences)
    profile = config.profile

    tailored = (
        f"# Tailored Resume -- {profile.get('full_name', 'YOUR NAME')}\n\n"
        f"_Prepared for: {job_row['title']} at {job_row['company']} "
        f"({job_row['url']})_\n\n"
        f"{'**NOTE: sample/placeholder job.**' if job_row['is_sample'] else ''}\n\n"
        f"## Targeting note\n"
        f"Relevant keywords found in this posting: {', '.join(matched) if matched else '(none matched)'}\n\n"
        f"## Base resume\n\n{base_resume}\n"
    )

    responses = (
        f"# Application responses -- {job_row['title']} at {job_row['company']}\n\n"
        f"No custom application questions were supplied for this source. "
        f"When a source provides screening questions, answers will be "
        f"generated here from verified profile facts only, and flagged for "
        f"approval before submission if a question is ambiguous or requires "
        f"a legal declaration.\n"
    )

    return {"resume_text": tailored, "responses_text": responses}
