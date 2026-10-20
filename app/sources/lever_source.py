"""Lever public Postings API adapter.

Endpoint: GET https://api.lever.co/v0/postings/{company}?mode=json

Lever's own public, unauthenticated postings API -- meant for exactly
this kind of consumption. VERIFIED LIVE on 2026-10-20: real calls
returned HTTP 200 with valid JSON for known Lever customers (e.g.
"palantir", with real posting content), and HTTP 404 for companies not
on Lever. None of the user's three target companies (Navi, InMobi,
Zomato) matched common Lever company-slug guesses -- InMobi has a
Greenhouse board instead (see greenhouse_source.py). Configure real,
verified company slugs in Settings -> Sources.
"""
from __future__ import annotations

import logging

import requests

from app.models import JobPosting
from app.sources.base import JobSource

logger = logging.getLogger(__name__)

BASE_URL = "https://api.lever.co/v0/postings/{company}"


class LeverCompanySource(JobSource):
    def __init__(self, company: str):
        self.company = company
        self.name = f"lever_{company}"

    def fetch(self, config) -> list[JobPosting]:
        url = BASE_URL.format(company=self.company)
        try:
            resp = requests.get(url, params={"mode": "json"}, timeout=20)
            resp.raise_for_status()
            postings_data = resp.json()
        except requests.RequestException as e:
            logger.error("Lever company '%s' fetch failed: %s", self.company, e)
            return []

        postings = []
        for job in postings_data:
            categories = job.get("categories") or {}
            postings.append(JobPosting(
                source=self.name,
                external_id=str(job.get("id", "")),
                url=job.get("hostedUrl", ""),
                title=job.get("text", ""),
                company=categories.get("team") or self.company,
                location=categories.get("location", ""),
                description=job.get("descriptionPlain") or job.get("description") or "",
                posted_at=None,  # Lever's createdAt is an epoch-ms int; left for a future pass
                is_sample=False,
                raw={"lever_posting_id": job.get("id"), "commitment": categories.get("commitment")},
            ))
        return postings
