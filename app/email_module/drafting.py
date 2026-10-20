"""Recruiter email drafting.

Template-based, and strict about never fabricating claims: it only ever
references the profile fields the user actually supplied, the specific job
(title/company/URL), and -- if present -- the recruiter's real name/title
from the evidence chain. It never says "I applied" (the pipeline only
drafts; it tracks separately whether an application was actually
submitted) and never invents shared connections or achievements.
"""
from __future__ import annotations

from app.models import EmailDraftContent


def draft_recruiter_email(job_row, recruiter_row, profile: dict) -> EmailDraftContent:
    full_name = profile.get("full_name", "YOUR NAME")
    headline = profile.get("headline", "")
    summary = profile.get("summary", "").strip()
    skills = profile.get("skills", [])

    recipient_name = recruiter_row["name"] if recruiter_row and recruiter_row["name"] else None
    greeting = f"Hi {recipient_name.split()[0]}," if recipient_name else "Hello,"

    subject = f"{full_name} -- interest in {job_row['title']} at {job_row['company']}"

    relationship_line = ""
    if recruiter_row and recruiter_row["relationship"] == "named_recruiter":
        relationship_line = (
            f"I saw you're the recruiter for the {job_row['title']} role at "
            f"{job_row['company']} ({job_row['url']})."
        )
    elif recruiter_row and recruiter_row["relationship"] == "hiring_manager":
        relationship_line = (
            f"I understand you lead the team hiring for {job_row['title']} at "
            f"{job_row['company']} ({job_row['url']})."
        )
    else:
        relationship_line = (
            f"I'm reaching out about the {job_row['title']} opening at "
            f"{job_row['company']} ({job_row['url']})."
        )

    skills_line = f" My background includes {', '.join(skills)}." if skills else ""

    body = (
        f"{greeting}\n\n"
        f"{relationship_line}\n\n"
        f"{summary}{skills_line}\n\n"
        f"I haven't submitted a formal application yet and wanted to check whether "
        f"you're the right person to discuss this role with, or if you could point "
        f"me to who is. I'd welcome the chance to be considered or to answer any "
        f"questions about my background.\n\n"
        f"Thank you for your time,\n"
        f"{full_name}"
        + (f"\n{headline}" if headline else "")
    )

    return EmailDraftContent(subject=subject, body=body)
