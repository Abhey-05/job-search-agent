"""Local/production Flask dashboard: review results, approve/reject,
run, pause, and edit profile/preferences/providers/execution/schedule --
all without touching source code. Protected by HTTP Basic Auth.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from flask import Flask, Response, redirect, render_template, request, url_for

from app import actions
from app.contacts.registry import get_contact_provider
from app.db import get_db
from app.email_module.registry import get_email_provider
from app.pipeline import Runner
from app.resume_store import has_real_resume, import_resume
from app.schedule_utils import compute_utc_cron
from app.settings import load_settings, save_settings_section

logger = logging.getLogger(__name__)
TEMPLATE_DIR = Path(__file__).parent / "templates"


def _expected_credentials() -> tuple[str, str]:
    user = os.environ.get("DASHBOARD_USERNAME")
    pw = os.environ.get("DASHBOARD_PASSWORD")
    if user and pw:
        return user, pw
    if os.environ.get("FLASK_ENV") == "production":
        raise RuntimeError(
            "DASHBOARD_USERNAME and DASHBOARD_PASSWORD must be set in production -- "
            "refusing to start with default credentials."
        )
    logger.warning(
        "DASHBOARD_USERNAME/DASHBOARD_PASSWORD not set -- using insecure local "
        "default admin/changeme. Set these env vars before deploying."
    )
    return "admin", "changeme"


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def create_app() -> Flask:
    flask_app = Flask(__name__, template_folder=str(TEMPLATE_DIR))
    flask_app.config["JSON_SORT_KEYS"] = False
    flask_app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB, generous for a resume PDF

    @flask_app.before_request
    def require_auth():
        auth = request.authorization
        expected_user, expected_pw = _expected_credentials()
        if not auth or auth.username != expected_user or auth.password != expected_pw:
            return Response(
                "Authentication required", 401,
                {"WWW-Authenticate": 'Basic realm="Job Search Agent"'},
            )

    def db():
        return get_db()

    # ----------------------------------------------------------- overview
    @flask_app.get("/")
    def index():
        d = db()
        cfg = load_settings(d)
        snapshot = d.dashboard_snapshot()
        paused = d.get_paused(default=cfg.paused)
        has_resume = has_real_resume(d)
        d.close()
        return render_template("index.html", mode=cfg.mode, paused=paused,
                                snapshot=snapshot, has_resume=has_resume)

    @flask_app.get("/jobs")
    def jobs():
        d = db()
        all_jobs = d.active_jobs()
        enriched = []
        for job in all_jobs:
            recruiters = d.get_recruiters_for_job(job["id"])
            recruiters_with_contacts = [(r, d.get_contact_for_recruiter(r["id"])) for r in recruiters]
            application = d.get_application_for_job(job["id"])
            email_draft = d.get_email_draft_for_job(job["id"])
            enriched.append({"job": job, "recruiters": recruiters_with_contacts,
                              "application": application, "email_draft": email_draft})
        enriched.sort(key=lambda e: (e["job"]["rank_score"] or 0), reverse=True)
        d.close()
        return render_template("jobs.html", items=enriched)

    @flask_app.get("/applications/<int:application_id>/resume.md")
    def download_resume(application_id):
        d = db()
        app_row = d.get_application(application_id)
        d.close()
        if app_row is None:
            return "Not found", 404
        return Response(app_row["resume_text"] or "", mimetype="text/markdown",
                         headers={"Content-Disposition": f"inline; filename=resume_{application_id}.md"})

    @flask_app.get("/applications/<int:application_id>/responses.md")
    def download_responses(application_id):
        d = db()
        app_row = d.get_application(application_id)
        d.close()
        if app_row is None:
            return "Not found", 404
        return Response(app_row["responses_text"] or "", mimetype="text/markdown",
                         headers={"Content-Disposition": f"inline; filename=responses_{application_id}.md"})

    # -------------------------------------------------------------- actions
    @flask_app.post("/emails/<int:draft_id>/approve")
    def approve_email_route(draft_id):
        d = db()
        actions.approve_email(d, load_settings(d), draft_id)
        d.close()
        return redirect(url_for("jobs"))

    @flask_app.post("/emails/<int:draft_id>/reject")
    def reject_email_route(draft_id):
        d = db()
        actions.reject_email(d, draft_id, note=request.form.get("note", ""))
        d.close()
        return redirect(url_for("jobs"))

    @flask_app.post("/applications/<int:application_id>/approve")
    def approve_application_route(application_id):
        d = db()
        actions.approve_application(d, load_settings(d), application_id)
        d.close()
        return redirect(url_for("jobs"))

    @flask_app.post("/applications/<int:application_id>/reject")
    def reject_application_route(application_id):
        d = db()
        actions.reject_application(d, application_id, note=request.form.get("note", ""))
        d.close()
        return redirect(url_for("jobs"))

    @flask_app.post("/applications/<int:application_id>/mark-submitted")
    def mark_submitted_route(application_id):
        d = db()
        actions.mark_application_submitted(d, application_id)
        d.close()
        return redirect(url_for("jobs"))

    @flask_app.post("/run")
    def run_route():
        d = db()
        cfg = load_settings(d)
        Runner(d, cfg).run()
        d.close()
        return redirect(url_for("index"))

    @flask_app.post("/pause")
    def pause_route():
        d = db()
        actions.pause(d)
        d.close()
        return redirect(url_for("index"))

    @flask_app.post("/resume")
    def resume_route():
        d = db()
        actions.resume(d)
        d.close()
        return redirect(url_for("index"))

    @flask_app.get("/runs")
    def runs():
        d = db()
        history = d.get_run_history(50)
        d.close()
        return render_template("runs.html", runs=history)

    @flask_app.get("/errors")
    def errors():
        d = db()
        failed_emails = d.email_drafts_by_status("failed")
        failed_apps = d.applications_by_status("failed")
        activity = [a for a in d.get_activity(500) if "failed" in a["action"]]
        d.close()
        return render_template("errors.html", failed_emails=failed_emails,
                                failed_apps=failed_apps, activity=activity)

    # ---------------------------------------------------------------- profile
    @flask_app.get("/profile")
    def profile_get():
        d = db()
        cfg = load_settings(d)
        resumes = d.list_resume_files()
        d.close()
        return render_template("profile.html", profile=cfg.profile, resumes=resumes)

    @flask_app.post("/profile")
    def profile_post():
        d = db()
        cfg = load_settings(d)
        profile = dict(cfg.profile)
        profile.update({
            "full_name": request.form.get("full_name", "").strip(),
            "email": request.form.get("email", "").strip(),
            "phone": request.form.get("phone", "").strip(),
            "location": request.form.get("location", "").strip(),
            "headline": request.form.get("headline", "").strip(),
            "summary": request.form.get("summary", "").strip(),
            "skills": _csv(request.form.get("skills", "")),
            "links": {
                "linkedin": request.form.get("linkedin", "").strip(),
                "portfolio": request.form.get("portfolio", "").strip(),
                "github": request.form.get("github", "").strip(),
            },
        })
        advanced_raw = request.form.get("advanced_json", "").strip()
        if advanced_raw:
            try:
                advanced = json.loads(advanced_raw)
                for key in ("education", "experience", "projects", "leadership", "achievements"):
                    if key in advanced:
                        profile[key] = advanced[key]
            except json.JSONDecodeError as e:
                d.close()
                return render_template("profile.html", profile=profile, resumes=d.list_resume_files(),
                                        error=f"Advanced JSON is invalid: {e}")
        save_settings_section(d, "profile", profile)

        uploaded = request.files.get("resume_file")
        if uploaded and uploaded.filename:
            content_type = uploaded.mimetype or "application/octet-stream"
            import_resume(d, load_settings(d), filename=uploaded.filename,
                          content_type=content_type, data=uploaded.read())

        d.close()
        return redirect(url_for("profile_get"))

    # ------------------------------------------------------------ preferences
    @flask_app.get("/preferences")
    def preferences_get():
        d = db()
        cfg = load_settings(d)
        d.close()
        return render_template("preferences.html", preferences=cfg.preferences)

    @flask_app.post("/preferences")
    def preferences_post():
        d = db()
        prefs = {
            "target_roles": _csv(request.form.get("target_roles", "")),
            "target_companies": _csv(request.form.get("target_companies", "")),
            "locations": _csv(request.form.get("locations", "")),
            "remote_ok": request.form.get("remote_ok") == "on",
            "min_salary": int(request.form["min_salary"]) if request.form.get("min_salary") else None,
            "seniority": _csv(request.form.get("seniority", "")),
            "keywords_boost": _csv(request.form.get("keywords_boost", "")),
            "keywords_exclude": _csv(request.form.get("keywords_exclude", "")),
            "ranking_weights": {
                "title_match": float(request.form.get("w_title", 0.35)),
                "company_match": float(request.form.get("w_company", 0.20)),
                "location_match": float(request.form.get("w_location", 0.15)),
                "keyword_boost": float(request.form.get("w_keyword", 0.15)),
                "recency": float(request.form.get("w_recency", 0.15)),
            },
        }
        save_settings_section(d, "preferences", prefs)
        d.close()
        return redirect(url_for("preferences_get"))

    # --------------------------------------------------------------- providers
    @flask_app.get("/providers")
    def providers_get():
        d = db()
        cfg = load_settings(d)
        contact_provider = get_contact_provider(cfg)
        email_provider = get_email_provider(cfg)
        health = {
            "contact_provider": contact_provider.name,
            "contact_configured": contact_provider.is_configured(),
            "contact_usage": contact_provider.usage_info(),
            "email_provider": email_provider.name,
            "email_configured": email_provider.is_configured(),
        }
        d.close()
        return render_template("providers.html", contacts=cfg.contacts, email=cfg.email, health=health)

    @flask_app.post("/providers")
    def providers_post():
        d = db()
        contacts = {
            "enabled_provider": request.form.get("enabled_provider") or None,
            "contactout": {"api_key_env": "CONTACTOUT_API_KEY"},
            "signalhire": {"api_key_env": "SIGNALHIRE_API_KEY"},
        }
        email = {
            "provider": request.form.get("email_provider", "mock"),
            "from_name": request.form.get("from_name", "").strip(),
            "from_email": request.form.get("from_email", "").strip(),
        }
        save_settings_section(d, "contacts", contacts)
        save_settings_section(d, "email", email)
        d.close()
        return redirect(url_for("providers_get"))

    # -------------------------------------------------------------- execution
    @flask_app.get("/execution")
    def execution_get():
        d = db()
        cfg = load_settings(d)
        paused = d.get_paused(default=cfg.paused)
        sources = cfg.sources.get("enabled", [])
        d.close()
        return render_template("execution.html", execution=cfg.execution, paused=paused, sources=sources)

    @flask_app.post("/execution")
    def execution_post():
        d = db()
        execution = {
            "mode": request.form.get("mode", "approval_required"),
            "paused": request.form.get("paused") == "on",
            "per_run_limits": {
                "applications": int(request.form.get("per_run_applications", 5)),
                "emails": int(request.form.get("per_run_emails", 5)),
            },
            "weekly_limits": {
                "applications": int(request.form.get("weekly_applications", 10)),
                "emails": int(request.form.get("weekly_emails", 10)),
            },
            "rules_based": {
                "allowed_auto_email_sources": _csv(request.form.get("allowed_auto_email_sources", "")),
                "allowed_auto_submit_sources": _csv(request.form.get("allowed_auto_submit_sources", "")),
            },
        }
        save_settings_section(d, "execution", execution)
        d.set_paused(execution["paused"])
        d.close()
        return redirect(url_for("execution_get"))

    # --------------------------------------------------------------- schedule
    @flask_app.get("/schedule")
    def schedule_get():
        d = db()
        cfg = load_settings(d)
        d.close()
        cron = compute_utc_cron(cfg.schedule)
        return render_template("schedule.html", schedule=cfg.schedule, utc_cron=cron)

    @flask_app.post("/schedule")
    def schedule_post():
        d = db()
        days = request.form.getlist("days")
        schedule = {
            "enabled": request.form.get("enabled") == "on",
            "days": days or ["mon", "wed", "fri"],
            "time": request.form.get("time", "08:00"),
            "timezone": request.form.get("timezone", "Asia/Kolkata"),
        }
        save_settings_section(d, "schedule", schedule)
        d.close()
        return redirect(url_for("schedule_get"))

    return flask_app
