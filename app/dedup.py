"""Normalization and deduplication of job postings.

Two postings are treated as the same underlying opportunity when their
normalized (title, company, location) triple matches, even if they came
from different sources with different external IDs. The first-seen job
row is kept as canonical; later duplicates are linked via `duplicate_of`
rather than deleted, so provenance (which boards reposted it) is preserved.
"""
from __future__ import annotations

import hashlib
import re

from app.models import JobPosting

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")

_TITLE_SYNONYMS = {
    "software engineer": "engineer",
    "backend software engineer": "backend engineer",
    "backend engineer, platform": "backend engineer",
}


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = _PUNCT_RE.sub("", text)
    text = _WS_RE.sub(" ", text)
    return text


def _normalize_title(title: str) -> str:
    norm = _normalize(title)
    return _TITLE_SYNONYMS.get(norm, norm)


def compute_job_id(posting: JobPosting) -> str:
    """Stable primary key: unique per (source, external_id)."""
    key = f"{posting.source}:{posting.external_id}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def compute_dedup_hash(posting: JobPosting) -> str:
    """Cross-source identity key: same role at same company/location."""
    key = f"{_normalize_title(posting.title)}|{_normalize(posting.company)}|{_normalize(posting.location or '')}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
