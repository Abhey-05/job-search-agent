"""Integration test: a full pipeline run against the sample sources, plus a
resumability check (running twice must not duplicate jobs, applications, or
email sends) and a check that research_only mode never sends/submits.
"""
from app import actions
from app.db import get_db
from app.pipeline import Runner
from app.settings import load_settings


def _make_runner(tmp_path, mode="approval_required"):
    db_path = tmp_path / "app.db"
    db = get_db(f"sqlite:///{db_path}")
    config = load_settings(db)
    config.raw["execution"]["mode"] = mode
    config.raw["execution"]["per_run_limits"] = {"applications": 10, "emails": 10}
    config.raw["execution"]["weekly_limits"] = {"applications": 10, "emails": 10}
    # Pin to the static sample sources only -- the real default settings
    # include a live Greenhouse board (verified in docs/INTEGRATIONS.md),
    # which must never be hit from a test.
    config.raw["sources"] = {
        "enabled": ["sample_board_a", "sample_board_b"],
        "greenhouse_boards": [], "lever_companies": [],
    }
    return db, config, Runner(db, config)


def test_full_run_discovers_ranks_matches_and_drafts(tmp_path):
    db, config, runner = _make_runner(tmp_path)

    summary = runner.run()

    # 5 postings total across both sample sources; 1 is a cross-source duplicate.
    assert summary.new_jobs == 5
    assert summary.duplicates == 1
    assert len(db.active_jobs()) == 4

    dup_row = db._one("SELECT * FROM jobs WHERE source='sample_board_b' AND external_id='b-5001'")
    assert dup_row["duplicate_of"] is not None

    for job in db.active_jobs():
        assert job["ranked_at"] is not None

    # Named recruiter / hiring manager jobs got a found contact; the job
    # with only a company-level team guess (no name) did not; the job that
    # hit a keywords_exclude match ("commission only") got no recruiter/outreach at all.
    pending_emails = db.email_drafts_by_status("pending_approval")
    assert len(pending_emails) == 2
    draft_only = db.email_drafts_by_status("draft")
    assert len(draft_only) == 1

    excluded_job = db._one("SELECT * FROM jobs WHERE company='ClickBoost Media'")
    assert excluded_job["rank_score"] == 0.0
    assert db.get_recruiters_for_job(excluded_job["id"]) == []
    assert db.get_application_for_job(excluded_job["id"]) is None

    assert summary.emails_sent == 0
    assert db.email_drafts_by_status("sent") == []
    pending_apps = db.applications_by_status("pending_approval")
    assert len(pending_apps) == 3

    db.close()


def test_second_run_is_resumable_and_does_not_duplicate(tmp_path):
    db, config, runner = _make_runner(tmp_path)

    runner.run()
    jobs_after_1 = len(db._all("SELECT 1 FROM jobs"))
    apps_after_1 = len(db._all("SELECT 1 FROM applications"))
    drafts_after_1 = len(db._all("SELECT 1 FROM email_drafts"))

    runner.run()
    jobs_after_2 = len(db._all("SELECT 1 FROM jobs"))
    apps_after_2 = len(db._all("SELECT 1 FROM applications"))
    drafts_after_2 = len(db._all("SELECT 1 FROM email_drafts"))

    assert jobs_after_2 == jobs_after_1
    assert apps_after_2 == apps_after_1
    assert drafts_after_2 == drafts_after_1
    assert db.email_drafts_by_status("sent") == []

    db.close()


def test_research_only_mode_never_sends_or_submits(tmp_path):
    db, config, runner = _make_runner(tmp_path, mode="research_only")

    summary = runner.run()

    assert summary.emails_sent == 0
    assert db.email_drafts_by_status("sent") == []
    assert db.applications_by_status("submitted") == []
    assert len(db.email_drafts_by_status("pending_approval")) == 2

    db.close()


def test_approve_email_action_sends_via_mock_provider_and_blocks_duplicate(tmp_path):
    db, config, runner = _make_runner(tmp_path)
    runner.run()

    draft = db.email_drafts_by_status("pending_approval")[0]
    result = actions.approve_email(db, config, draft["id"])
    assert result["ok"] is True

    sent = db.get_email_draft(draft["id"])
    assert sent["status"] == "sent"
    assert sent["provider"] == "mock"
    assert sent["provider_message_id"].startswith("mock-")

    result2 = actions.approve_email(db, config, draft["id"])
    assert result2["ok"] is False

    db.close()


def test_pause_blocks_approval(tmp_path):
    db, config, runner = _make_runner(tmp_path)
    runner.run()

    actions.pause(db)
    draft = db.email_drafts_by_status("pending_approval")[0]
    result = actions.approve_email(db, config, draft["id"])
    assert result["ok"] is False
    assert "paused" in result["error"].lower()

    db.close()


def test_resume_upload_is_used_in_application_package(tmp_path):
    from app.resume_store import import_resume

    db, config, runner = _make_runner(tmp_path, mode="research_only")
    import_resume(db, config, filename="resume.txt", content_type="text/plain",
                  data=b"REAL RESUME CONTENT: experienced product manager.")

    runner.run()
    app_row = db.applications_by_status("prepared")
    app_row = app_row[0] if app_row else db.applications_by_status("pending_approval")[0]
    assert "REAL RESUME CONTENT" in app_row["resume_text"]

    db.close()
