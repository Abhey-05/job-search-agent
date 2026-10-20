"""Covers the manual-import workflow, CSV import, dedup across import vs.
discovery, free Greenhouse/Lever source adapters (network calls mocked),
and -- the most important property of this change -- that a real
(non-sample) imported job NEVER gets an automated/guessed contact email.
"""
from unittest.mock import patch

from app import import_jobs
from app.db import get_db
from app.pipeline import Runner, RunSummary
from app.settings import load_settings


def _runner(tmp_path):
    db = get_db(f"sqlite:///{tmp_path / 'app.db'}")
    config = load_settings(db)
    config.raw["sources"] = {"enabled": [], "greenhouse_boards": [], "lever_companies": []}
    return db, config, Runner(db, config)


def test_import_without_recruiter_info_leaves_contact_blank(tmp_path):
    db, config, runner = _runner(tmp_path)
    run_id = db.start_run(config.mode)
    summary = RunSummary(run_id=run_id, mode=config.mode)

    posting = import_jobs.build_posting(
        title="Product Manager", company="Acme Corp", location="Remote",
        url="https://www.linkedin.com/jobs/view/12345",
        description="Own product strategy and analytics for our platform.",
    )
    import_jobs.import_posting(db, posting, run_id)
    runner.process_existing(run_id, summary)

    job = db.active_jobs()[0]
    assert job["is_sample"] == 0
    # No recruiter evidence was given at all -> no recruiter row, nothing to guess.
    assert db.get_recruiters_for_job(job["id"]) == []
    draft = db.get_email_draft_for_job(job["id"])
    assert draft is not None
    assert draft["to_email"] is None  # never guessed
    assert draft["status"] == "draft"  # never queued for sending without a real recipient

    db.close()


def test_import_with_user_provided_recruiter_email_is_used_verbatim(tmp_path):
    db, config, runner = _runner(tmp_path)
    run_id = db.start_run(config.mode)
    summary = RunSummary(run_id=run_id, mode=config.mode)

    posting = import_jobs.build_posting(
        title="Product Analyst", company="Acme Corp", location="Remote",
        url="https://www.linkedin.com/jobs/view/99999",
        description="Analytics role.",
        recruiter_name="Jordan Lee", recruiter_title="Technical Recruiter",
        recruiter_email="jordan.lee@acmecorp.com",
        recruiter_profile_url="https://www.linkedin.com/in/jordanlee",
    )
    import_jobs.import_posting(db, posting, run_id)
    runner.process_existing(run_id, summary)

    job = db.active_jobs()[0]
    recruiters = db.get_recruiters_for_job(job["id"])
    assert len(recruiters) == 1
    assert recruiters[0]["profile_url"] == "https://www.linkedin.com/in/jordanlee"

    contact = db.get_contact_for_recruiter(recruiters[0]["id"])
    assert contact["email"] == "jordan.lee@acmecorp.com"
    assert contact["provider"] == "user_provided"
    assert contact["email_status"] == "unverified"  # never claimed "verified" without real verification

    draft = db.get_email_draft_for_job(job["id"])
    assert draft["to_email"] == "jordan.lee@acmecorp.com"
    assert draft["status"] == "pending_approval"  # approval-gated, never auto-sent

    db.close()


def test_duplicate_url_import_is_idempotent(tmp_path):
    db, config, runner = _runner(tmp_path)
    run_id = db.start_run(config.mode)

    posting = import_jobs.build_posting(
        title="Product Manager", company="Acme Corp", location="Remote",
        url="https://www.linkedin.com/jobs/view/55555", description="desc",
    )
    r1 = import_jobs.import_posting(db, posting, run_id)
    r2 = import_jobs.import_posting(db, posting, run_id)

    assert r1["is_new"] is True
    assert r2["is_new"] is False
    assert len(db._all("SELECT 1 FROM jobs")) == 1

    db.close()


def test_import_dedups_against_an_auto_discovered_job_by_title_company_location(tmp_path):
    """A job found via LinkedIn and pasted in should collapse with the
    same role discovered automatically from a Greenhouse board, even
    though the source/external_id/URL all differ."""
    from app.dedup import compute_dedup_hash, compute_job_id
    from app.models import JobPosting

    db, config, runner = _runner(tmp_path)
    run_id = db.start_run(config.mode)

    discovered = JobPosting(
        source="greenhouse_acme", external_id="gh-1", url="https://boards.greenhouse.io/acme/jobs/1",
        title="Product Manager", company="Acme Corp", location="Remote",
        description="desc", is_sample=False, raw={},
    )
    job_id = compute_job_id(discovered)
    db.upsert_job(job_id, compute_dedup_hash(discovered), discovered, run_id)

    imported = import_jobs.build_posting(
        title="Product Manager", company="Acme Corp", location="Remote",
        url="https://www.linkedin.com/jobs/view/77777", description="desc",
    )
    result = import_jobs.import_posting(db, imported, run_id)

    assert result["duplicate_of"] == job_id
    assert len(db.active_jobs()) == 1  # the imported one is linked, not shown separately

    db.close()


def test_csv_import_parses_expected_columns():
    csv_text = (
        "title,company,location,url,description,recruiter_name,recruiter_email\n"
        "Product Manager,Beta Inc,Remote,https://example.com/job/1,Own the roadmap,,\n"
        "Product Analyst,Beta Inc,Bangalore,https://example.com/job/2,Analytics role,Sam Patel,sam@beta.com\n"
    )
    postings = import_jobs.parse_csv(csv_text)
    assert len(postings) == 2
    assert postings[0].title == "Product Manager"
    assert postings[1].named_recruiter == {"name": "Sam Patel", "title": None, "email": "sam@beta.com"}


def test_greenhouse_source_parses_mocked_response():
    from app.sources.greenhouse_source import GreenhouseBoardSource

    fake_response = {
        "jobs": [{
            "id": 123, "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
            "title": "Product Manager", "company_name": "Acme",
            "location": {"name": "Remote"}, "content": "<p>Own the <b>roadmap</b></p>",
            "first_published": "2026-10-01T00:00:00Z", "updated_at": "2026-10-02T00:00:00Z",
            "departments": [],
        }]
    }

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return fake_response

    with patch("app.sources.greenhouse_source.requests.get", return_value=FakeResp()):
        postings = GreenhouseBoardSource("acme").fetch(config=None)

    assert len(postings) == 1
    assert postings[0].title == "Product Manager"
    assert postings[0].source == "greenhouse_acme"
    assert "roadmap" in postings[0].description
    assert "<" not in postings[0].description  # HTML stripped


def test_lever_source_parses_mocked_response():
    from app.sources.lever_source import LeverCompanySource

    fake_postings = [{
        "id": "abc123", "hostedUrl": "https://jobs.lever.co/acme/abc123",
        "text": "Product Analyst", "categories": {"team": "Product", "location": "Remote"},
        "descriptionPlain": "Analyze funnels and run experiments.",
    }]

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return fake_postings

    with patch("app.sources.lever_source.requests.get", return_value=FakeResp()):
        postings = LeverCompanySource("acme").fetch(config=None)

    assert len(postings) == 1
    assert postings[0].title == "Product Analyst"
    assert postings[0].source == "lever_acme"
    assert postings[0].company == "Product"
