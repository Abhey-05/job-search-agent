"""Two mock source adapters used for development/testing.

Hand-written sample postings -- clearly flagged `is_sample=True` -- shaped
around Abhey's actual target roles (Product Manager / Product Analyst)
and target companies (Navi, InMobi, Zomato), so the demo run is
meaningful rather than generic. They exercise every downstream code path:
cross-source duplicates, every tier of the recruiter-evidence chain, a
keyword-exclusion case, and a mix of ranking fits.

Real adapters (a company careers API, Greenhouse, Lever, etc.) implement
the same JobSource interface and get added to app/sources/registry.py;
nothing else in the pipeline needs to change.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import JobPosting
from app.sources.base import JobSource


def _iso_days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).date().isoformat()


class SampleBoardA(JobSource):
    """Simulates a job board API with named recruiters."""

    name = "sample_board_a"

    def fetch(self, config) -> list[JobPosting]:
        return [
            JobPosting(
                source=self.name,
                external_id="a-1001",
                url="https://sample-board-a.example.com/jobs/1001",
                title="Senior Product Manager",
                company="Navi",
                location="Remote",
                description=(
                    "Own product strategy for a lending/fintech surface. Heavy use of "
                    "experimentation, A/B testing, and analytics to drive growth and "
                    "marketplace outcomes."
                ),
                posted_at=_iso_days_ago(2),
                is_sample=True,
                named_recruiter={"name": "Jordan Lee", "title": "Technical Recruiter"},
                raw={"note": "SAMPLE DATA"},
            ),
            JobPosting(
                source=self.name,
                external_id="a-1002",
                url="https://sample-board-a.example.com/jobs/1002",
                title="Product Analyst",
                company="QuickCart Marketplace",
                location="Bangalore, India",
                description=(
                    "Drive marketplace optimization through data-driven product "
                    "analytics, SQL-based experimentation analysis, and growth metrics."
                ),
                posted_at=_iso_days_ago(5),
                is_sample=True,
                hiring_manager={"name": "Priya Shah", "title": "Product Lead, Marketplace"},
                raw={"note": "SAMPLE DATA"},
            ),
            JobPosting(
                source=self.name,
                external_id="a-1003",
                url="https://sample-board-a.example.com/jobs/1003",
                title="Growth Marketing Associate",
                company="ClickBoost Media",
                location="Mumbai, India",
                description="Commission only role driving referral growth campaigns.",
                posted_at=_iso_days_ago(10),
                is_sample=True,
                careers_email="careers@clickboostmedia.example.com",
                raw={"note": "SAMPLE DATA - intentionally excluded-keyword job"},
            ),
        ]


class SampleBoardB(JobSource):
    """Simulates a second board that reposts some of the same openings,
    to exercise cross-source dedup, plus one company-recruiter-only case."""

    name = "sample_board_b"

    def fetch(self, config) -> list[JobPosting]:
        return [
            JobPosting(
                source=self.name,
                external_id="b-5001",
                url="https://sample-board-b.example.com/postings/5001",
                title="Senior Product Manager",
                company="Navi",
                location="Remote",
                description=(
                    "Own product strategy for a lending/fintech surface. Heavy use of "
                    "experimentation, A/B testing, and analytics to drive growth and "
                    "marketplace outcomes."
                ),
                posted_at=_iso_days_ago(1),
                is_sample=True,
                # Same role as sample_board_a/a-1001 reposted by an aggregator.
                # The aggregator account is NOT the hiring recruiter -- this is
                # exactly the "do not assume reposter == recruiter" case.
                poster={"name": "JobBot Aggregator", "title": "Automated repost"},
                poster_is_recruiter=False,
                raw={"note": "SAMPLE DATA - cross-source duplicate of a-1001"},
            ),
            JobPosting(
                source=self.name,
                external_id="b-5002",
                url="https://sample-board-b.example.com/postings/5002",
                title="Technical Product Manager",
                company="InMobi",
                location="Remote",
                description=(
                    "Technical PM role for an ad-tech platform team; product strategy "
                    "work spans AI-assisted targeting and marketplace experimentation."
                ),
                posted_at=_iso_days_ago(3),
                is_sample=True,
                # No named recruiter or hiring manager surfaced by this source;
                # a relevant recruiter at the company can still be reasonably
                # inferred and verified downstream.
                raw={
                    "note": "SAMPLE DATA - no named poster",
                    "likely_recruiting_team": "InMobi Talent Acquisition",
                },
            ),
        ]
