"""Persistence layer, built on SQLAlchemy Core so the exact same code runs
against local SQLite (dev/tests) and managed PostgreSQL (production) --
selected purely by the DATABASE_URL connection string.

Design goals carried over from the original build:
  - Resumability: every job row carries a timestamp column per pipeline
    stage (ranked_at, recruiter_matched_at, ...). A stage is "done" for a
    job once its timestamp is non-null, so an interrupted run resumes by
    re-querying "jobs where <stage>_at is null" -- nothing already
    completed is repeated.
  - No reliance on the application's local filesystem for anything that
    must survive a redeploy: generated resumes/application responses are
    stored as TEXT columns in the `applications` table, and uploaded
    resumes are stored as bytes in `resume_files` -- both live in the
    database, not on disk, so a dashboard (web) and scheduled run
    (cron/worker) running as separate, filesystem-isolated services still
    see the same data.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Row

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def default_database_url() -> str:
    data_dir = PROJECT_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{data_dir / 'app.db'}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _autopk(dialect: str) -> str:
    return "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"


def _schema_statements(dialect: str) -> list[str]:
    pk = _autopk(dialect)
    return [
        f"""CREATE TABLE IF NOT EXISTS runs (
            id {pk},
            mode TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            summary_json TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            dedup_hash TEXT NOT NULL,
            source TEXT NOT NULL,
            external_id TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT,
            description TEXT,
            posted_at TEXT,
            is_sample INTEGER NOT NULL DEFAULT 0,
            raw_json TEXT,
            first_seen_run_id INTEGER,
            last_seen_run_id INTEGER,
            discovered_at TEXT NOT NULL,
            rank_score REAL,
            rank_explanation TEXT,
            ranked_at TEXT,
            recruiter_matched_at TEXT,
            contact_looked_up_at TEXT,
            package_prepared_at TEXT,
            email_drafted_at TEXT,
            duplicate_of TEXT REFERENCES jobs(id)
        )""",
        f"""CREATE TABLE IF NOT EXISTS recruiters (
            id {pk},
            job_id TEXT NOT NULL REFERENCES jobs(id),
            name TEXT,
            title TEXT,
            company TEXT,
            relationship TEXT NOT NULL,
            evidence_url TEXT,
            evidence_note TEXT,
            confidence REAL,
            created_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS contacts (
            id {pk},
            recruiter_id INTEGER NOT NULL REFERENCES recruiters(id),
            provider TEXT NOT NULL,
            email TEXT,
            email_status TEXT,
            phone TEXT,
            confidence REAL,
            credits_used INTEGER DEFAULT 0,
            raw_json TEXT,
            looked_up_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS applications (
            id {pk},
            job_id TEXT NOT NULL REFERENCES jobs(id),
            status TEXT NOT NULL DEFAULT 'draft',
            resume_text TEXT,
            responses_text TEXT,
            prepared_at TEXT,
            decided_at TEXT,
            submitted_at TEXT,
            follow_up_date TEXT,
            notes TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS email_drafts (
            id {pk},
            job_id TEXT NOT NULL REFERENCES jobs(id),
            recruiter_id INTEGER REFERENCES recruiters(id),
            to_email TEXT,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            provider TEXT,
            provider_message_id TEXT,
            created_at TEXT NOT NULL,
            decided_at TEXT,
            sent_at TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS activity_log (
            id {pk},
            run_id INTEGER,
            entity_type TEXT NOT NULL,
            entity_id TEXT,
            action TEXT NOT NULL,
            detail TEXT,
            created_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS resume_files (
            id {pk},
            filename TEXT NOT NULL,
            content_type TEXT NOT NULL,
            data BYTEA_OR_BLOB,
            extracted_text TEXT,
            uploaded_at TEXT NOT NULL
        )""".replace("BYTEA_OR_BLOB", "BYTEA" if dialect == "postgresql" else "BLOB"),
        """CREATE TABLE IF NOT EXISTS app_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_jobs_dedup_hash ON jobs(dedup_hash)",
        "CREATE INDEX IF NOT EXISTS idx_recruiters_job ON recruiters(job_id)",
        "CREATE INDEX IF NOT EXISTS idx_contacts_recruiter ON contacts(recruiter_id)",
        "CREATE INDEX IF NOT EXISTS idx_applications_job ON applications(job_id)",
        "CREATE INDEX IF NOT EXISTS idx_email_drafts_job ON email_drafts(job_id)",
    ]


_ENGINE_CACHE: dict[str, Any] = {}
_SCHEMA_INITIALIZED: set[str] = set()


class Database:
    """One instance per request/call-site; engines (and the connection
    pool they hold) are cached by URL at module scope so repeated calls
    from the Flask dashboard don't reopen the SQLite file or re-run schema
    DDL on every request."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        if database_url not in _ENGINE_CACHE:
            _ENGINE_CACHE[database_url] = create_engine(database_url, future=True)
        self.engine = _ENGINE_CACHE[database_url]
        self.dialect = self.engine.dialect.name  # "sqlite" | "postgresql"
        self.conn = self.engine.connect()
        if database_url not in _SCHEMA_INITIALIZED:
            if self.dialect == "sqlite":
                self.conn.execute(text("PRAGMA foreign_keys = ON"))
            for stmt in _schema_statements(self.dialect):
                self.conn.execute(text(stmt))
            self.conn.commit()
            _SCHEMA_INITIALIZED.add(database_url)

    def close(self):
        self.conn.close()  # returns the connection to the pool; engine stays alive

    def _exec(self, sql: str, params: Optional[dict] = None):
        return self.conn.execute(text(sql), params or {})

    def _one(self, sql: str, params: Optional[dict] = None):
        return self._exec(sql, params).mappings().fetchone()

    def _all(self, sql: str, params: Optional[dict] = None) -> list:
        return self._exec(sql, params).mappings().fetchall()

    # ---------------------------------------------------------------- runs
    def start_run(self, mode: str) -> int:
        row = self._one(
            "INSERT INTO runs (mode, started_at, status) VALUES (:mode, :started_at, 'running') "
            "RETURNING id",
            {"mode": mode, "started_at": _now()},
        )
        self.conn.commit()
        return row["id"]

    def finish_run(self, run_id: int, status: str, summary: dict):
        self._exec(
            "UPDATE runs SET finished_at = :finished_at, status = :status, summary_json = :summary WHERE id = :id",
            {"finished_at": _now(), "status": status, "summary": json.dumps(summary), "id": run_id},
        )
        self.conn.commit()

    def get_run_history(self, limit: int = 20) -> list:
        return self._all("SELECT * FROM runs ORDER BY id DESC LIMIT :limit", {"limit": limit})

    def get_run(self, run_id: int):
        return self._one("SELECT * FROM runs WHERE id = :id", {"id": run_id})

    # ------------------------------------------------------------ activity
    def log_activity(self, run_id: Optional[int], entity_type: str, entity_id: Any,
                      action: str, detail: str = ""):
        self._exec(
            "INSERT INTO activity_log (run_id, entity_type, entity_id, action, detail, created_at) "
            "VALUES (:run_id, :entity_type, :entity_id, :action, :detail, :created_at)",
            {"run_id": run_id, "entity_type": entity_type,
             "entity_id": str(entity_id) if entity_id is not None else None,
             "action": action, "detail": detail, "created_at": _now()},
        )
        self.conn.commit()

    def get_activity(self, limit: int = 200) -> list:
        return self._all("SELECT * FROM activity_log ORDER BY id DESC LIMIT :limit", {"limit": limit})

    # ------------------------------------------------------------------ jobs
    def upsert_job(self, job_id: str, dedup_hash: str, posting, run_id: int) -> tuple[str, bool]:
        existing = self._one("SELECT id FROM jobs WHERE id = :id", {"id": job_id})
        if existing:
            self._exec(
                "UPDATE jobs SET last_seen_run_id = :run_id WHERE id = :id",
                {"run_id": run_id, "id": job_id},
            )
            self.conn.commit()
            return job_id, False

        raw_payload = dict(posting.raw)
        raw_payload.update({
            "named_recruiter": posting.named_recruiter,
            "hiring_manager": posting.hiring_manager,
            "poster": posting.poster,
            "poster_is_recruiter": posting.poster_is_recruiter,
            "careers_email": posting.careers_email,
        })
        self._exec(
            """INSERT INTO jobs (
                id, dedup_hash, source, external_id, url, title, company, location,
                description, posted_at, is_sample, raw_json,
                first_seen_run_id, last_seen_run_id, discovered_at
            ) VALUES (
                :id, :dedup_hash, :source, :external_id, :url, :title, :company, :location,
                :description, :posted_at, :is_sample, :raw_json,
                :run_id, :run_id, :discovered_at
            )""",
            {
                "id": job_id, "dedup_hash": dedup_hash, "source": posting.source,
                "external_id": posting.external_id, "url": posting.url, "title": posting.title,
                "company": posting.company, "location": posting.location,
                "description": posting.description, "posted_at": posting.posted_at,
                "is_sample": int(posting.is_sample), "raw_json": json.dumps(raw_payload),
                "run_id": run_id, "discovered_at": _now(),
            },
        )
        self.conn.commit()
        return job_id, True

    def mark_duplicate(self, job_id: str, duplicate_of: str):
        self._exec("UPDATE jobs SET duplicate_of = :dup WHERE id = :id",
                    {"dup": duplicate_of, "id": job_id})
        self.conn.commit()

    def find_by_dedup_hash(self, dedup_hash: str, exclude_id: Optional[str] = None) -> list:
        rows = self._all(
            "SELECT * FROM jobs WHERE dedup_hash = :h ORDER BY discovered_at ASC", {"h": dedup_hash}
        )
        if exclude_id:
            rows = [r for r in rows if r["id"] != exclude_id]
        return rows

    def get_job(self, job_id: str):
        return self._one("SELECT * FROM jobs WHERE id = :id", {"id": job_id})

    def active_jobs(self) -> list:
        return self._all("SELECT * FROM jobs WHERE duplicate_of IS NULL ORDER BY discovered_at DESC")

    def jobs_needing_stage(self, column: str) -> list:
        assert column in (
            "ranked_at", "recruiter_matched_at", "contact_looked_up_at",
            "package_prepared_at", "email_drafted_at",
        )
        return self._all(
            f"SELECT * FROM jobs WHERE duplicate_of IS NULL AND {column} IS NULL "
            "ORDER BY discovered_at ASC"
        )

    def update_job_rank(self, job_id: str, score: float, explanation: list[str]):
        self._exec(
            "UPDATE jobs SET rank_score = :score, rank_explanation = :expl, ranked_at = :at WHERE id = :id",
            {"score": score, "expl": json.dumps(explanation), "at": _now(), "id": job_id},
        )
        self.conn.commit()

    def mark_stage_done(self, job_id: str, column: str):
        assert column in (
            "recruiter_matched_at", "contact_looked_up_at",
            "package_prepared_at", "email_drafted_at",
        )
        self._exec(f"UPDATE jobs SET {column} = :at WHERE id = :id", {"at": _now(), "id": job_id})
        self.conn.commit()

    def jobs_since_run(self, run_id: int) -> list:
        return self._all(
            "SELECT * FROM jobs WHERE first_seen_run_id = :run_id AND duplicate_of IS NULL",
            {"run_id": run_id},
        )

    # ------------------------------------------------------------ recruiters
    def add_recruiter(self, job_id: str, name: Optional[str], title: Optional[str],
                       company: Optional[str], relationship: str, evidence_url: str,
                       evidence_note: str, confidence: float) -> int:
        row = self._one(
            """INSERT INTO recruiters (job_id, name, title, company, relationship,
                evidence_url, evidence_note, confidence, created_at)
               VALUES (:job_id, :name, :title, :company, :relationship,
                :evidence_url, :evidence_note, :confidence, :created_at)
               RETURNING id""",
            {"job_id": job_id, "name": name, "title": title, "company": company,
             "relationship": relationship, "evidence_url": evidence_url,
             "evidence_note": evidence_note, "confidence": confidence, "created_at": _now()},
        )
        self.conn.commit()
        return row["id"]

    def get_recruiters_for_job(self, job_id: str) -> list:
        return self._all("SELECT * FROM recruiters WHERE job_id = :job_id ORDER BY id ASC",
                          {"job_id": job_id})

    def get_recruiter(self, recruiter_id: int):
        return self._one("SELECT * FROM recruiters WHERE id = :id", {"id": recruiter_id})

    # -------------------------------------------------------------- contacts
    def add_contact(self, recruiter_id: int, provider: str, email: Optional[str],
                     email_status: Optional[str], phone: Optional[str],
                     confidence: float, credits_used: int, raw: dict) -> int:
        row = self._one(
            """INSERT INTO contacts (recruiter_id, provider, email, email_status, phone,
                confidence, credits_used, raw_json, looked_up_at)
               VALUES (:recruiter_id, :provider, :email, :email_status, :phone,
                :confidence, :credits_used, :raw_json, :looked_up_at)
               RETURNING id""",
            {"recruiter_id": recruiter_id, "provider": provider, "email": email,
             "email_status": email_status, "phone": phone, "confidence": confidence,
             "credits_used": credits_used, "raw_json": json.dumps(raw), "looked_up_at": _now()},
        )
        self.conn.commit()
        return row["id"]

    def get_contact_for_recruiter(self, recruiter_id: int):
        return self._one(
            "SELECT * FROM contacts WHERE recruiter_id = :id ORDER BY id DESC LIMIT 1",
            {"id": recruiter_id},
        )

    # --------------------------------------------------------- applications
    def add_application(self, job_id: str, status: str = "draft") -> int:
        row = self._one(
            "INSERT INTO applications (job_id, status) VALUES (:job_id, :status) RETURNING id",
            {"job_id": job_id, "status": status},
        )
        self.conn.commit()
        return row["id"]

    def update_application(self, application_id: int, **fields):
        if not fields:
            return
        cols = ", ".join(f"{k} = :{k}" for k in fields)
        params = dict(fields)
        params["id"] = application_id
        self._exec(f"UPDATE applications SET {cols} WHERE id = :id", params)
        self.conn.commit()

    def get_application_for_job(self, job_id: str):
        return self._one(
            "SELECT * FROM applications WHERE job_id = :job_id ORDER BY id DESC LIMIT 1",
            {"job_id": job_id},
        )

    def get_application(self, application_id: int):
        return self._one("SELECT * FROM applications WHERE id = :id", {"id": application_id})

    def applications_by_status(self, status: str) -> list:
        return self._all("SELECT * FROM applications WHERE status = :status ORDER BY id DESC",
                          {"status": status})

    def applications_submitted_since(self, since_iso: str) -> int:
        row = self._one(
            "SELECT COUNT(*) AS n FROM applications WHERE status = 'submitted' AND submitted_at >= :since",
            {"since": since_iso},
        )
        return row["n"]

    # --------------------------------------------------------- email drafts
    def add_email_draft(self, job_id: str, recruiter_id: Optional[int], subject: str,
                         body: str, to_email: Optional[str] = None, status: str = "draft") -> int:
        row = self._one(
            """INSERT INTO email_drafts (job_id, recruiter_id, to_email, subject, body, status, created_at)
               VALUES (:job_id, :recruiter_id, :to_email, :subject, :body, :status, :created_at)
               RETURNING id""",
            {"job_id": job_id, "recruiter_id": recruiter_id, "to_email": to_email,
             "subject": subject, "body": body, "status": status, "created_at": _now()},
        )
        self.conn.commit()
        return row["id"]

    def update_email_draft(self, draft_id: int, **fields):
        if not fields:
            return
        cols = ", ".join(f"{k} = :{k}" for k in fields)
        params = dict(fields)
        params["id"] = draft_id
        self._exec(f"UPDATE email_drafts SET {cols} WHERE id = :id", params)
        self.conn.commit()

    def get_email_draft_for_job(self, job_id: str):
        return self._one(
            "SELECT * FROM email_drafts WHERE job_id = :job_id ORDER BY id DESC LIMIT 1",
            {"job_id": job_id},
        )

    def get_email_draft(self, draft_id: int):
        return self._one("SELECT * FROM email_drafts WHERE id = :id", {"id": draft_id})

    def email_drafts_by_status(self, status: str) -> list:
        return self._all("SELECT * FROM email_drafts WHERE status = :status ORDER BY id DESC",
                          {"status": status})

    def emails_sent_since(self, since_iso: str) -> int:
        row = self._one(
            "SELECT COUNT(*) AS n FROM email_drafts WHERE status = 'sent' AND sent_at >= :since",
            {"since": since_iso},
        )
        return row["n"]

    def existing_sent_email_for_recipient_and_job(self, job_id: str):
        return self._one(
            "SELECT * FROM email_drafts WHERE job_id = :job_id AND status = 'sent' LIMIT 1",
            {"job_id": job_id},
        )

    # ------------------------------------------------------------ resumes
    def add_resume_file(self, filename: str, content_type: str, data: bytes,
                         extracted_text: str) -> int:
        row = self._one(
            """INSERT INTO resume_files (filename, content_type, data, extracted_text, uploaded_at)
               VALUES (:filename, :content_type, :data, :extracted_text, :uploaded_at)
               RETURNING id""",
            {"filename": filename, "content_type": content_type, "data": data,
             "extracted_text": extracted_text, "uploaded_at": _now()},
        )
        self.conn.commit()
        return row["id"]

    def get_latest_resume_file(self):
        return self._one("SELECT * FROM resume_files ORDER BY id DESC LIMIT 1")

    def get_resume_file(self, resume_id: int):
        return self._one("SELECT * FROM resume_files WHERE id = :id", {"id": resume_id})

    def list_resume_files(self) -> list:
        return self._all(
            "SELECT id, filename, content_type, uploaded_at, length(extracted_text) AS text_len "
            "FROM resume_files ORDER BY id DESC"
        )

    # ---------------------------------------------------------------- state
    def get_state(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self._one("SELECT value FROM app_state WHERE key = :key", {"key": key})
        return row["value"] if row else default

    def set_state(self, key: str, value: str):
        self._exec(
            "INSERT INTO app_state (key, value) VALUES (:key, :value) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            {"key": key, "value": value},
        )
        self.conn.commit()

    def get_paused(self, default: bool = False) -> bool:
        value = self.get_state("paused")
        if value is None:
            return default
        return value == "true"

    def set_paused(self, paused: bool):
        self.set_state("paused", "true" if paused else "false")

    # ------------------------------------------------------------- dashboard
    def dashboard_snapshot(self) -> dict:
        last_run = self._one(
            "SELECT * FROM runs WHERE status != 'running' ORDER BY id DESC LIMIT 1"
        )
        new_since_last = []
        if last_run:
            new_since_last = self.jobs_since_run(last_run["id"])
        return {
            "jobs": self.active_jobs(),
            "new_since_last_run": new_since_last,
            "pending_emails": self.email_drafts_by_status("pending_approval"),
            "pending_applications": self.applications_by_status("pending_approval"),
            "sent_emails": self.email_drafts_by_status("sent"),
            "submitted_applications": self.applications_by_status("submitted"),
            "failed_emails": self.email_drafts_by_status("failed"),
            "failed_applications": self.applications_by_status("failed"),
            "runs": self.get_run_history(10),
            "activity": self.get_activity(50),
        }


def get_db(database_url: Optional[str] = None) -> Database:
    url = database_url or os.environ.get("DATABASE_URL") or default_database_url()
    return Database(url)
