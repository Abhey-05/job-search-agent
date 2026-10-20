"""Recruiter / hiring-contact identification.

Implements the priority order from spec:
  1. A named recruiter explicitly associated with the opening.
  2. A hiring manager / talent-acquisition professional associated with the team.
  3. A relevant recruiter at the company, reasonably verified.
  4. An official recruitment/careers contact, if no individual is identifiable.

Crucially: the account that *reposted* a listing (an aggregator, a bot, a
second job board mirroring the original) is never treated as the hiring
recruiter. `poster_is_recruiter` must be explicitly true for a poster to be
used as evidence at all, and even then it only ever reaches tier 3, never
tier 1.

Everything returned here is "evidence to act on", not a verified identity --
confidence is explicit and the evidence_url/evidence_note always point back
to where the claim came from so a human can check it before an email goes
out.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.models import JobPosting


@dataclass
class RecruiterMatch:
    name: Optional[str]
    title: Optional[str]
    company: str
    relationship: str   # named_recruiter | hiring_manager | company_recruiter | careers_contact
    evidence_url: str
    evidence_note: str
    confidence: float
    careers_email: Optional[str] = None  # set only for the careers_contact tier
    provided_email: Optional[str] = None   # set only when the user supplied it at import time
    profile_url: Optional[str] = None       # LinkedIn (or other) profile URL, if the user supplied one


def match_recruiter(job_row) -> Optional[RecruiterMatch]:
    """job_row is a sqlite3.Row from the jobs table; raw_json holds the
    source-reported evidence fields captured on JobPosting."""
    import json

    raw = json.loads(job_row["raw_json"] or "{}")
    url = job_row["url"]
    company = job_row["company"]

    named_recruiter = raw.get("named_recruiter")
    if named_recruiter and named_recruiter.get("name"):
        note = "Named explicitly as the recruiter on the job posting."
        if named_recruiter.get("email"):
            note += " Email was supplied directly by the user, not looked up or guessed."
        return RecruiterMatch(
            name=named_recruiter["name"],
            title=named_recruiter.get("title"),
            company=company,
            relationship="named_recruiter",
            evidence_url=url,
            evidence_note=note,
            confidence=0.9,
            provided_email=named_recruiter.get("email"),
            profile_url=named_recruiter.get("profile_url"),
        )

    hiring_manager = raw.get("hiring_manager")
    if hiring_manager and hiring_manager.get("name"):
        note = "Named as the hiring manager / team lead for this opening."
        if hiring_manager.get("email"):
            note += " Email was supplied directly by the user, not looked up or guessed."
        return RecruiterMatch(
            name=hiring_manager["name"],
            title=hiring_manager.get("title"),
            company=company,
            relationship="hiring_manager",
            evidence_url=url,
            evidence_note=note,
            confidence=0.75,
            provided_email=hiring_manager.get("email"),
            profile_url=hiring_manager.get("profile_url"),
        )

    poster = raw.get("poster")
    poster_is_recruiter = bool(raw.get("poster_is_recruiter"))
    if poster and poster.get("name") and poster_is_recruiter:
        return RecruiterMatch(
            name=poster["name"],
            title=poster.get("title"),
            company=company,
            relationship="company_recruiter",
            evidence_url=url,
            evidence_note=(
                "Posted the opening and is flagged as a recruiter at the "
                "hiring company (not a reposting aggregator)."
            ),
            confidence=0.6,
        )
    if poster and poster.get("name") and not poster_is_recruiter:
        # Explicitly NOT trusted as the recruiter -- e.g. an aggregator/bot
        # repost. Fall through to the careers-contact tier instead.
        pass

    likely_team = raw.get("likely_recruiting_team")
    if likely_team:
        return RecruiterMatch(
            name=None,
            title=likely_team,
            company=company,
            relationship="company_recruiter",
            evidence_url=url,
            evidence_note=(
                f"No individual named on the posting; inferred that "
                f"'{likely_team}' is the relevant recruiting team at {company}. "
                "Needs verification before outreach."
            ),
            confidence=0.35,
        )

    careers_email = raw.get("careers_email")
    if careers_email:
        return RecruiterMatch(
            name=None,
            title="Careers / Talent Acquisition",
            company=company,
            relationship="careers_contact",
            evidence_url=url,
            evidence_note="No individual identifiable; falling back to the official careers contact.",
            confidence=0.5,
            careers_email=careers_email,
        )

    return None
