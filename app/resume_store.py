"""Resume ingestion and retrieval.

Resumes are stored as bytes in the `resume_files` table (not on disk) so
the dashboard -- which may run as a separate process/container from the
scheduled worker -- always sees the same, latest uploaded resume, and so
nothing is lost on a redeploy. Text is extracted once at upload time (via
pypdf for PDFs, decoded directly for .txt/.md) and cached alongside the
bytes so the pipeline never has to re-parse a PDF on every run.
"""
from __future__ import annotations

from app import settings as settings_module

PLACEHOLDER_RESUME_TEXT = (
    "PLACEHOLDER RESUME -- no resume has been uploaded yet.\n\n"
    "Upload one from the dashboard's Profile page, or run:\n"
    "  python -m app import-resume /path/to/resume.pdf\n"
)


def extract_text(filename: str, content_type: str, data: bytes) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf") or content_type == "application/pdf":
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages).strip()
    # .txt / .md / anything else: best-effort decode
    return data.decode("utf-8", errors="replace").strip()


def import_resume(db, config, filename: str, content_type: str, data: bytes) -> int:
    text = extract_text(filename, content_type, data)
    resume_id = db.add_resume_file(filename=filename, content_type=content_type,
                                    data=data, extracted_text=text)
    profile = dict(config.profile)
    profile["resume_file_id"] = resume_id
    settings_module.save_settings_section(db, "profile", profile)
    db.log_activity(None, "resume", resume_id, "uploaded", filename)
    return resume_id


def get_current_resume_text(db) -> str:
    resume = db.get_latest_resume_file()
    if resume is None or not resume["extracted_text"]:
        return PLACEHOLDER_RESUME_TEXT
    return resume["extracted_text"]


def has_real_resume(db) -> bool:
    return db.get_latest_resume_file() is not None
