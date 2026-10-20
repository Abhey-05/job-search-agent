"""Manual job import: the human-assisted counterpart to automated
discovery. The user finds a listing themselves (via the LinkedIn search
links this app generates and opens in their own browser, or anywhere
else) and pastes its URL/details in, or uploads a small CSV of several at
once. Nothing here ever fetches, scrapes, or authenticates against
LinkedIn or any other site -- it only accepts data the user already has
in front of them.

Imported jobs are inserted into the exact same `jobs` table, with the
exact same dedup/rank/recruiter-match/contact/package/draft pipeline
applied afterward (see app/pipeline.py's `process_existing`) -- there is
no separate code path for "imported" vs "discovered" jobs past this
point, only a `source` value that says which one it was.
"""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime, timezone

from app.dedup import compute_dedup_hash, compute_job_id
from app.models import JobPosting

MANUAL_SOURCE = "manual_import"

CSV_COLUMNS = (
    "title", "company", "location", "url", "description", "posted_at",
    "recruiter_name", "recruiter_title", "is_hiring_manager",
    "recruiter_email", "recruiter_profile_url", "careers_email",
)


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.strip().lower().encode("utf-8")).hexdigest()[:20]


def build_posting(
    title: str, company: str, location: str, url: str, description: str,
    posted_at: str | None = None,
    recruiter_name: str | None = None, recruiter_title: str | None = None,
    is_hiring_manager: bool = False,
    recruiter_email: str | None = None, recruiter_profile_url: str | None = None,
    careers_email: str | None = None,
    found_via: str = "",
) -> JobPosting:
    named_recruiter = None
    hiring_manager = None
    if recruiter_name:
        contact = {"name": recruiter_name, "title": recruiter_title}
        if recruiter_email:
            contact["email"] = recruiter_email
        if recruiter_profile_url:
            contact["profile_url"] = recruiter_profile_url
        if is_hiring_manager:
            hiring_manager = contact
        else:
            named_recruiter = contact

    return JobPosting(
        source=MANUAL_SOURCE,
        external_id=_url_hash(url),
        url=url.strip(),
        title=title.strip(),
        company=company.strip(),
        location=location.strip(),
        description=description.strip(),
        posted_at=posted_at or None,
        is_sample=False,
        named_recruiter=named_recruiter,
        hiring_manager=hiring_manager,
        careers_email=careers_email or None,
        raw={"imported_at": datetime.now(timezone.utc).isoformat(), "found_via": found_via},
    )


def import_posting(db, posting: JobPosting, run_id: int) -> dict:
    """Inserts one posting through the same dedup logic discovery uses.
    Returns {"job_id", "is_new", "duplicate_of"}."""
    job_id = compute_job_id(posting)
    dedup_hash = compute_dedup_hash(posting)
    _, is_new = db.upsert_job(job_id, dedup_hash, posting, run_id)

    duplicate_of = None
    if is_new:
        siblings = db.find_by_dedup_hash(dedup_hash, exclude_id=job_id)
        canonical = next((r for r in siblings if r["duplicate_of"] is None), None)
        if canonical is not None:
            db.mark_duplicate(job_id, canonical["id"])
            duplicate_of = canonical["id"]
        db.log_activity(run_id, "job", job_id, "imported", f"{posting.title} @ {posting.company}")
    return {"job_id": job_id, "is_new": is_new, "duplicate_of": duplicate_of}


def parse_csv(file_text: str) -> list[JobPosting]:
    """Parses a user-authored CSV (see CSV_COLUMNS for the header this
    expects -- only title/company/location/url/description are required,
    the rest are optional). This is NOT a parser for any specific external
    export format -- define the CSV however is convenient for you; this
    just expects those column names."""
    reader = csv.DictReader(io.StringIO(file_text))
    postings = []
    for row in reader:
        if not row.get("title") or not row.get("url"):
            continue
        is_hm = str(row.get("is_hiring_manager", "")).strip().lower() in ("1", "true", "yes")
        postings.append(build_posting(
            title=row.get("title", ""), company=row.get("company", ""),
            location=row.get("location", ""), url=row.get("url", ""),
            description=row.get("description", ""), posted_at=row.get("posted_at") or None,
            recruiter_name=row.get("recruiter_name") or None,
            recruiter_title=row.get("recruiter_title") or None,
            is_hiring_manager=is_hm,
            recruiter_email=row.get("recruiter_email") or None,
            recruiter_profile_url=row.get("recruiter_profile_url") or None,
            careers_email=row.get("careers_email") or None,
            found_via="csv_import",
        ))
    return postings
