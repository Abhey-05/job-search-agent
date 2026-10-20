"""Human-in-the-loop actions: approve/reject a single email draft or
application. These are the only code paths that actually send an email or
mark an application submitted outside of rules-based auto-execution --
approving one item here never implies approval for any other item, run, or
future job, by design (per spec section F).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db import Database
from app.email_module.registry import get_email_provider


def approve_email(db: Database, config, draft_id: int) -> dict:
    draft = db.get_email_draft(draft_id)
    if draft is None:
        return {"ok": False, "error": f"No email draft with id {draft_id}"}
    if draft["status"] not in ("pending_approval", "draft"):
        return {"ok": False, "error": f"Draft {draft_id} is '{draft['status']}', not awaiting approval"}
    if not draft["to_email"]:
        return {"ok": False, "error": "No recipient email on this draft yet; cannot send."}
    if db.get_paused(default=config.paused):
        return {"ok": False, "error": "Execution is paused; resume before approving sends."}

    already_sent = db.existing_sent_email_for_recipient_and_job(draft["job_id"])
    if already_sent and already_sent["id"] != draft_id:
        return {"ok": False, "error": "An email was already sent for this job; blocking duplicate outreach."}

    provider = get_email_provider(config)
    try:
        message_id = provider.send(draft["to_email"], draft["subject"], draft["body"])
    except Exception as e:
        db.update_email_draft(draft_id, status="failed")
        db.log_activity(None, "email_draft", draft_id, "send_failed", str(e))
        return {"ok": False, "error": str(e)}

    now = datetime.now(timezone.utc).isoformat()
    db.update_email_draft(draft_id, status="sent", provider=provider.name,
                           provider_message_id=message_id, sent_at=now, decided_at=now)
    db.log_activity(None, "email_draft", draft_id, "approved_and_sent", message_id)
    return {"ok": True, "message_id": message_id}


def reject_email(db: Database, draft_id: int, note: str = "") -> dict:
    draft = db.get_email_draft(draft_id)
    if draft is None:
        return {"ok": False, "error": f"No email draft with id {draft_id}"}
    db.update_email_draft(draft_id, status="rejected", decided_at=datetime.now(timezone.utc).isoformat())
    db.log_activity(None, "email_draft", draft_id, "rejected", note)
    return {"ok": True}


def approve_application(db: Database, config, application_id: int) -> dict:
    app_row = db.get_application(application_id)
    if app_row is None:
        return {"ok": False, "error": f"No application with id {application_id}"}
    if app_row["status"] not in ("pending_approval", "prepared"):
        return {"ok": False, "error": f"Application {application_id} is '{app_row['status']}', not awaiting approval"}
    if db.get_paused(default=config.paused):
        return {"ok": False, "error": "Execution is paused; resume before approving submissions."}

    # No authorized, site-specific submission adapter exists yet (see
    # docs/INTEGRATIONS.md). Approving here records the decision and marks
    # it ready; it intentionally does not fabricate a real ATS submission.
    now = datetime.now(timezone.utc).isoformat()
    db.update_application(application_id, status="approved", decided_at=now)
    db.log_activity(None, "application", application_id, "approved",
                     "Marked approved. No automated submission adapter is wired up yet -- "
                     "submit manually using the prepared package, then mark as submitted.")
    return {"ok": True, "note": "Approved. Manual submission required until a real ATS adapter exists."}


def mark_application_submitted(db: Database, application_id: int, follow_up_in_days: int = 7) -> dict:
    app_row = db.get_application(application_id)
    if app_row is None:
        return {"ok": False, "error": f"No application with id {application_id}"}
    now = datetime.now(timezone.utc)
    follow_up = (now + timedelta(days=follow_up_in_days)).date().isoformat()
    db.update_application(application_id, status="submitted", submitted_at=now.isoformat(),
                           follow_up_date=follow_up)
    db.log_activity(None, "application", application_id, "submitted_manually", f"follow_up={follow_up}")
    return {"ok": True}


def reject_application(db: Database, application_id: int, note: str = "") -> dict:
    app_row = db.get_application(application_id)
    if app_row is None:
        return {"ok": False, "error": f"No application with id {application_id}"}
    db.update_application(application_id, status="rejected", decided_at=datetime.now(timezone.utc).isoformat(),
                           notes=note)
    db.log_activity(None, "application", application_id, "rejected", note)
    return {"ok": True}


def pause(db: Database):
    db.set_paused(True)
    db.log_activity(None, "run", None, "paused_by_user", "")


def resume(db: Database):
    db.set_paused(False)
    db.log_activity(None, "run", None, "resumed_by_user", "")
