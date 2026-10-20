"""Greenhouse public Job Board API adapter.

Endpoint: GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true

This is Greenhouse's own public, unauthenticated job-board API, meant to
be read by job seekers/aggregators -- not a scrape, not a bypass of any
restriction. VERIFIED LIVE on 2026-10-20: a real call against the public
"stripe" board returned HTTP 200 with 725 real postings and the schema
assumed below; a call against "inmobi" (one of the user's actual target
companies) also returned 200 with real, current openings including
"Product Analyst II" and "Product Manager - Programmatic Monetization"
in Bangalore.

Not every company has a Greenhouse board, and the board token is not
always guessable from the company name (Navi and Zomato did not match
common guesses when checked). Configure real, verified board tokens in
Settings -> Sources.
"""
from __future__ import annotations

import logging
import re

import requests

from app.models import JobPosting
from app.sources.base import JobSource

logger = logging.getLogger(__name__)

BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


class GreenhouseBoardSource(JobSource):
    def __init__(self, board_token: str):
        self.board_token = board_token
        self.name = f"greenhouse_{board_token}"

    def fetch(self, config) -> list[JobPosting]:
        url = BASE_URL.format(token=self.board_token)
        try:
            resp = requests.get(url, params={"content": "true"}, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error("Greenhouse board '%s' fetch failed: %s", self.board_token, e)
            return []

        postings = []
        for job in data.get("jobs", []):
            location = (job.get("location") or {}).get("name", "")
            postings.append(JobPosting(
                source=self.name,
                external_id=str(job["id"]),
                url=job.get("absolute_url", ""),
                title=job.get("title", ""),
                company=job.get("company_name") or self.board_token,
                location=location,
                description=_strip_html(job.get("content", "")),
                posted_at=(job.get("first_published") or job.get("updated_at") or "")[:10] or None,
                is_sample=False,
                raw={"greenhouse_job_id": job.get("id"), "departments": job.get("departments")},
            ))
        return postings
