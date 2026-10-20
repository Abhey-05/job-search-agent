"""Pipeline orchestration for a single `python -m app run` invocation.

Resumability model: every stage below queries the DB for jobs that have
NOT yet completed that stage (the relevant `*_at` column is NULL) and only
marks the stage complete after it succeeds for that job. If the process is
killed mid-run, the next run's queries naturally pick up exactly where it
left off -- nothing already-completed is repeated, and nothing is lost.

Each job is processed independently inside a try/except per stage: one
job's failure is logged to activity_log and that job's stage is left
incomplete (so it's retried next run) without aborting the rest of the run.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.application_prep import prepare_application_package
from app.contacts.registry import get_contact_provider
from app.db import Database
from app.dedup import compute_dedup_hash, compute_job_id
from app.email_module.drafting import draft_recruiter_email
from app.email_module.registry import get_email_provider
from app.models import ContactSearchQuery
from app.ranking import rank_job
from app.recruiter_matching import match_recruiter
from app.settings import Settings
from app.sources.registry import get_enabled_sources

logger = logging.getLogger(__name__)


def _is_excluded(job_row) -> bool:
    """True when ranking hit a hard keyword exclusion (preferences.keywords_exclude).
    Excluded jobs are still recorded and visible in the dashboard, but the
    pipeline does not spend recruiter/contact/outreach effort on them."""
    return "EXCLUDED" in (job_row["rank_explanation"] or "")


_RELATIONSHIP_PRIORITY = {
    "named_recruiter": 0,
    "hiring_manager": 1,
    "company_recruiter": 2,
    "careers_contact": 3,
}


@dataclass
class RunSummary:
    run_id: int
    mode: str
    discovered: int = 0
    new_jobs: int = 0
    duplicates: int = 0
    ranked: int = 0
    recruiters_matched: int = 0
    contacts_looked_up: int = 0
    packages_prepared: int = 0
    emails_drafted: int = 0
    emails_sent: int = 0
    applications_submitted: int = 0
    queued_for_approval: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _week_start_iso() -> str:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=now.weekday())
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.isoformat()


class Runner:
    def __init__(self, db: Database, config: Settings):
        self.db = db
        self.config = config

    # ------------------------------------------------------------- discover
    def discover_and_normalize(self, run_id: int, summary: RunSummary):
        sources = get_enabled_sources(self.config)
        for source in sources:
            try:
                postings = source.fetch(self.config)
            except Exception as e:
                logger.exception("Source %s failed", source.name)
                summary.errors.append(f"source:{source.name}: {e}")
                self.db.log_activity(run_id, "source", source.name, "fetch_failed", str(e))
                continue

            summary.discovered += len(postings)
            for posting in postings:
                job_id = compute_job_id(posting)
                dedup_hash = compute_dedup_hash(posting)
                _, is_new = self.db.upsert_job(job_id, dedup_hash, posting, run_id)
                if not is_new:
                    continue
                summary.new_jobs += 1
                self.db.log_activity(run_id, "job", job_id, "discovered",
                                      f"{posting.title} @ {posting.company} via {posting.source}")

                siblings = self.db.find_by_dedup_hash(dedup_hash, exclude_id=job_id)
                canonical = next((r for r in siblings if r["duplicate_of"] is None), None)
                if canonical is not None:
                    self.db.mark_duplicate(job_id, canonical["id"])
                    summary.duplicates += 1
                    self.db.log_activity(
                        run_id, "job", job_id, "marked_duplicate",
                        f"duplicate of {canonical['id']} ({canonical['source']} repost)",
                    )

    # ---------------------------------------------------------------- rank
    def rank_jobs(self, run_id: int, summary: RunSummary):
        for job in self.db.jobs_needing_stage("ranked_at"):
            try:
                score, explanation = rank_job(job, self.config.preferences)
                self.db.update_job_rank(job["id"], score, explanation)
                summary.ranked += 1
            except Exception as e:
                logger.exception("Ranking failed for job %s", job["id"])
                summary.errors.append(f"rank:{job['id']}: {e}")
                self.db.log_activity(run_id, "job", job["id"], "rank_failed", str(e))

    # ----------------------------------------------------------- recruiter
    def match_recruiters(self, run_id: int, summary: RunSummary):
        for job in self.db.jobs_needing_stage("recruiter_matched_at"):
            try:
                if _is_excluded(job):
                    self.db.log_activity(run_id, "job", job["id"], "excluded_by_keyword_filter",
                                          "skipping recruiter match/outreach")
                    self.db.mark_stage_done(job["id"], "recruiter_matched_at")
                    continue
                match = match_recruiter(job)
                if match is not None:
                    recruiter_id = self.db.add_recruiter(
                        job_id=job["id"], name=match.name, title=match.title,
                        company=match.company, relationship=match.relationship,
                        evidence_url=match.evidence_url, evidence_note=match.evidence_note,
                        confidence=match.confidence,
                    )
                    if match.careers_email:
                        self.db.add_contact(
                            recruiter_id=recruiter_id, provider="source",
                            email=match.careers_email, email_status="unverified",
                            phone=None, confidence=match.confidence, credits_used=0,
                            raw={"source": "official careers contact on posting"},
                        )
                    summary.recruiters_matched += 1
                    self.db.log_activity(run_id, "job", job["id"], "recruiter_matched",
                                          f"{match.relationship}: {match.name or match.title}")
                else:
                    self.db.log_activity(run_id, "job", job["id"], "no_recruiter_found", "")
                self.db.mark_stage_done(job["id"], "recruiter_matched_at")
            except Exception as e:
                logger.exception("Recruiter matching failed for job %s", job["id"])
                summary.errors.append(f"recruiter_match:{job['id']}: {e}")
                self.db.log_activity(run_id, "job", job["id"], "recruiter_match_failed", str(e))

    # ------------------------------------------------------------- contact
    def lookup_contacts(self, run_id: int, summary: RunSummary):
        provider = get_contact_provider(self.config)
        touched_provider = False
        for job in self.db.jobs_needing_stage("contact_looked_up_at"):
            try:
                recruiters = self.db.get_recruiters_for_job(job["id"])
                for recruiter in recruiters:
                    existing = self.db.get_contact_for_recruiter(recruiter["id"])
                    if existing is not None:
                        continue  # already have a contact (e.g. careers_email from matching)
                    if not recruiter["name"]:
                        self.db.log_activity(run_id, "recruiter", recruiter["id"],
                                              "contact_skipped", "no individual name to search")
                        continue

                    touched_provider = True
                    query = ContactSearchQuery(
                        name=recruiter["name"], company=recruiter["company"],
                        title=recruiter["title"],
                    )
                    result = provider.search_person(query)
                    if result is None:
                        self.db.log_activity(run_id, "recruiter", recruiter["id"],
                                              "contact_lookup_none", f"provider={provider.name}")
                        continue

                    if result.email and result.email_status == "unverified" and provider.name != "contactout":
                        verified = provider.verify_email(result.email)
                        if verified == "valid":
                            result.email_status = "verified"

                    self.db.add_contact(
                        recruiter_id=recruiter["id"], provider=result.source,
                        email=result.email, email_status=result.email_status,
                        phone=result.phone, confidence=result.confidence,
                        credits_used=result.credits_used, raw=result.raw,
                    )
                    summary.contacts_looked_up += 1
                    self.db.log_activity(run_id, "recruiter", recruiter["id"], "contact_found",
                                          f"{result.email or '(none)'} [{result.email_status}] via {result.source}")
                self.db.mark_stage_done(job["id"], "contact_looked_up_at")
            except Exception as e:
                logger.exception("Contact lookup failed for job %s", job["id"])
                summary.errors.append(f"contact_lookup:{job['id']}: {e}")
                self.db.log_activity(run_id, "job", job["id"], "contact_lookup_failed", str(e))

        if touched_provider:
            self.db.log_activity(run_id, "contact_provider", provider.name, "usage_info",
                                  str(provider.usage_info()))

    # ------------------------------------------------------------- package
    def prepare_packages(self, run_id: int, summary: RunSummary):
        for job in self.db.jobs_needing_stage("package_prepared_at"):
            try:
                if _is_excluded(job):
                    self.db.log_activity(run_id, "job", job["id"], "excluded_by_keyword_filter",
                                          "skipping application package")
                    self.db.mark_stage_done(job["id"], "package_prepared_at")
                    continue
                result = prepare_application_package(job, self.config, self.db)
                application_id = self.db.add_application(job["id"], status="prepared")
                self.db.update_application(
                    application_id, resume_text=result["resume_text"],
                    responses_text=result["responses_text"],
                    prepared_at=datetime.now(timezone.utc).isoformat(),
                )
                summary.packages_prepared += 1
                self.db.log_activity(run_id, "application", application_id, "prepared",
                                      f"{len(result['resume_text'])} chars")
                self.db.mark_stage_done(job["id"], "package_prepared_at")
            except Exception as e:
                logger.exception("Package prep failed for job %s", job["id"])
                summary.errors.append(f"package_prep:{job['id']}: {e}")
                self.db.log_activity(run_id, "job", job["id"], "package_prep_failed", str(e))

    # ----------------------------------------------------------------- email
    def _best_recruiter_with_contact(self, job_id: str):
        recruiters = self.db.get_recruiters_for_job(job_id)
        ranked = sorted(recruiters, key=lambda r: _RELATIONSHIP_PRIORITY.get(r["relationship"], 9))
        for r in ranked:
            contact = self.db.get_contact_for_recruiter(r["id"])
            if contact is not None:
                return r, contact
        return (ranked[0], None) if ranked else (None, None)

    def draft_emails(self, run_id: int, summary: RunSummary):
        for job in self.db.jobs_needing_stage("email_drafted_at"):
            try:
                if _is_excluded(job):
                    self.db.log_activity(run_id, "job", job["id"], "excluded_by_keyword_filter",
                                          "skipping outreach email")
                    self.db.mark_stage_done(job["id"], "email_drafted_at")
                    continue
                recruiter, contact = self._best_recruiter_with_contact(job["id"])
                draft = draft_recruiter_email(job, recruiter, self.config.profile)
                to_email = contact["email"] if contact else None
                status = "pending_approval" if to_email else "draft"
                draft_id = self.db.add_email_draft(
                    job_id=job["id"],
                    recruiter_id=recruiter["id"] if recruiter else None,
                    subject=draft.subject, body=draft.body, to_email=to_email,
                    status=status,
                )
                summary.emails_drafted += 1
                self.db.log_activity(run_id, "email_draft", draft_id, "drafted",
                                      f"to={to_email or '(no email found yet)'}")
                self.db.mark_stage_done(job["id"], "email_drafted_at")
            except Exception as e:
                logger.exception("Email drafting failed for job %s", job["id"])
                summary.errors.append(f"email_draft:{job['id']}: {e}")
                self.db.log_activity(run_id, "job", job["id"], "email_draft_failed", str(e))

    # ------------------------------------------------------------- execute
    def _within_limits(self, kind: str) -> bool:
        limits = self.config.execution
        per_run = limits.get("per_run_limits", {}).get(kind, 0)
        weekly = limits.get("weekly_limits", {}).get(kind, 0)
        since = _week_start_iso()
        used_this_week = (
            self.db.emails_sent_since(since) if kind == "emails"
            else self.db.applications_submitted_since(since)
        )
        return used_this_week < weekly and per_run > 0

    def build_and_execute_queue(self, run_id: int, summary: RunSummary):
        mode = self.config.mode
        paused = self.db.get_paused(default=self.config.paused)

        pending_emails = self.db.email_drafts_by_status("pending_approval")
        pending_apps = self.db.applications_by_status("prepared")

        if mode == "research_only":
            summary.queued_for_approval += 0
            self.db.log_activity(run_id, "run", run_id, "research_only",
                                  "Prepared drafts/packages only; no sends or submissions in this mode.")
            return

        if paused:
            self.db.log_activity(run_id, "run", run_id, "paused",
                                  "Execution paused by user; nothing sent or submitted this run.")
            return

        email_provider = get_email_provider(self.config)
        per_run_email_limit = self.config.execution.get("per_run_limits", {}).get("emails", 0)
        per_run_app_limit = self.config.execution.get("per_run_limits", {}).get("applications", 0)

        auto_email_sources = set(
            self.config.execution.get("rules_based", {}).get("allowed_auto_email_sources", [])
        )

        emails_executed_this_run = 0
        for draft in pending_emails:
            if emails_executed_this_run >= per_run_email_limit:
                break
            job = self.db.get_job(draft["job_id"])
            already_sent = self.db.existing_sent_email_for_recipient_and_job(draft["job_id"])
            if already_sent:
                self.db.update_email_draft(draft["id"], status="rejected",
                                            decided_at=datetime.now(timezone.utc).isoformat())
                self.db.log_activity(run_id, "email_draft", draft["id"], "duplicate_outreach_blocked",
                                      "an email was already sent for this job")
                continue

            if mode == "rules_based" and job and job["source"] in auto_email_sources and self._within_limits("emails"):
                approved = True
            elif mode == "rules_based":
                approved = False  # not covered by configured rules -> needs manual approval
            else:
                approved = False  # approval_required: never auto-execute

            if not approved:
                summary.queued_for_approval += 1
                self.db.log_activity(run_id, "email_draft", draft["id"], "queued_for_approval", "")
                continue

            try:
                message_id = email_provider.send(draft["to_email"], draft["subject"], draft["body"])
                self.db.update_email_draft(
                    draft["id"], status="sent", provider=email_provider.name,
                    provider_message_id=message_id,
                    sent_at=datetime.now(timezone.utc).isoformat(),
                    decided_at=datetime.now(timezone.utc).isoformat(),
                )
                summary.emails_sent += 1
                emails_executed_this_run += 1
                self.db.log_activity(run_id, "email_draft", draft["id"], "sent", message_id)
            except Exception as e:
                self.db.update_email_draft(draft["id"], status="failed")
                summary.errors.append(f"send_email:{draft['id']}: {e}")
                self.db.log_activity(run_id, "email_draft", draft["id"], "send_failed", str(e))

        auto_submit_sources = set(
            self.config.execution.get("rules_based", {}).get("allowed_auto_submit_sources", [])
        )
        apps_executed_this_run = 0
        for application in pending_apps:
            if apps_executed_this_run >= per_run_app_limit:
                break
            job = self.db.get_job(application["job_id"])

            if mode == "rules_based" and job and job["source"] in auto_submit_sources and self._within_limits("applications"):
                approved = True
            else:
                approved = False  # no real submission adapter is authorized yet (see docs/INTEGRATIONS.md)

            if not approved:
                self.db.update_application(application["id"], status="pending_approval")
                summary.queued_for_approval += 1
                self.db.log_activity(run_id, "application", application["id"], "queued_for_approval", "")
                continue

            # No site-specific, authorized auto-submit adapter exists yet.
            # Rules-based mode intentionally has nothing to put in
            # allowed_auto_submit_sources until one is built and the terms
            # of that site/integration are confirmed to permit it.
            self.db.log_activity(run_id, "application", application["id"], "auto_submit_unavailable",
                                  "No authorized submission adapter configured for this source.")

    # ------------------------------------------------------------------ run
    def run(self) -> RunSummary:
        mode = self.config.mode
        run_id = self.db.start_run(mode)
        summary = RunSummary(run_id=run_id, mode=mode)
        try:
            self.discover_and_normalize(run_id, summary)
            self.rank_jobs(run_id, summary)
            self.match_recruiters(run_id, summary)
            self.lookup_contacts(run_id, summary)
            self.prepare_packages(run_id, summary)
            self.draft_emails(run_id, summary)
            self.build_and_execute_queue(run_id, summary)
            status = "completed" if not summary.errors else "completed_with_errors"
            self.db.finish_run(run_id, status, summary.as_dict())
        except Exception as e:
            logger.exception("Run %s failed", run_id)
            summary.errors.append(f"run:{e}")
            self.db.finish_run(run_id, "failed", summary.as_dict())
        return summary
