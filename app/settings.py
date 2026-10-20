"""DB-backed application settings.

Replaces the earlier YAML-file config. Profile, preferences, source/
contact/email provider choice, execution mode, and schedule are all
editable from the dashboard and stored in the `app_state` key/value table
(under `settings:<section>` keys) -- so they persist across redeploys and
are never hardcoded into business logic.

True secrets (API keys, DB connection string, dashboard credentials) stay
in environment variables / the platform's secret store -- never in the
database or in git. `resolve_env_secret` is the one place business logic
reads them, always by looking up the *name* of an env var that a settings
section points to, never a literal key.
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass

VALID_MODES = ("research_only", "approval_required", "rules_based")

SETTINGS_SECTIONS = (
    "profile", "preferences", "sources", "email", "execution", "schedule", "notifications",
)

# Seeded into the database the first time it's read with no stored value.
# Abhey's confirmed profile/preferences as of October 2026 -- treat as
# initial defaults, fully editable from the dashboard without touching code.
DEFAULT_SETTINGS = {
    "profile": {
        "full_name": "Abhey Garg",
        "email": "",
        "phone": "",
        "location": "",
        "headline": "Product Manager | B.Tech Electrical Engineering, IIT Hyderabad",
        "summary": (
            "B.Tech Electrical Engineering (IC Design and Technology) student at IIT "
            "Hyderabad, graduating 2027, focused on product management and product "
            "analytics. Management Consulting internship at Accenture Strategy & "
            "Consulting (AI-enabled OT security audits, workforce-intelligence "
            "analytics). Product/data projects spanning A/B test decision engines, "
            "experimentation analysis, and large-scale e-commerce behavioral data "
            "(100M+ events). Led Tinkerers' Lab at IIT Hyderabad, a 50-member team "
            "that raised Rs. 25L+ in sponsorships."
        ),
        "skills": [
            "SQL", "Python", "NumPy", "Pandas", "Matplotlib", "scikit-learn", "C", "C++",
            "FastAPI", "REST APIs", "MySQL", "Redis", "Kafka", "Git", "GitHub", "Excel",
            "PowerPoint", "Power BI", "Tableau", "Jira", "Confluence", "Notion",
        ],
        "education": [
            {"institution": "IIT Hyderabad", "degree": "B.Tech Electrical Engineering (IC Design and Technology)",
             "expected_graduation": "2027", "detail": "CGPA 8.3"},
        ],
        "experience": [
            {"company": "Accenture Strategy & Consulting", "title": "Management Consulting Intern",
             "dates": "May-Jul 2026",
             "highlights": [
                 "AI-enabled OT Security Audit: reduced manual audit effort by 70-80%; "
                 "standardized 150+ controls across 15+ standards and 8 jurisdictions.",
                 "Workforce Intelligence: reduced agent schedule creation time by 90%; "
                 "delivered 6+ Genesys Cloud workforce-management demos.",
             ]},
        ],
        "projects": [
            {"name": "Product Intelligence & A/B Test Decision Engine",
             "detail": "Experimentation analysis, conversion funnels, statistical significance, "
                       "confidence intervals, guardrail metrics, uplift models, AI-assisted insights."},
            {"name": "ProductPulse",
             "detail": "109.9M+ e-commerce events, 5.3M users, 23M sessions, 206K+ products, "
                       "39+ SQL analyses, DuckDB, Streamlit, Plotly."},
        ],
        "leadership": [
            "Overall Head of THRUST at Tinkerers' Lab, IIT Hyderabad: led a 50-member core "
            "team, raised Rs.25L+ in sponsorships, launched a hackathon with a Rs.10L+ prize pool.",
            "Core, Placement Cell, Office of Career Services, IIT Hyderabad: coordinated "
            "20+ internship and placement drives.",
        ],
        "links": {"linkedin": "", "portfolio": "", "github": ""},
        "resume_file_id": None,  # set once a resume is uploaded/imported; see app/resume_store.py
    },
    "preferences": {
        "target_roles": [
            "Product Manager", "Technical Product Manager", "Product Analyst",
            "Associate Product Manager", "Product Analytics",
        ],
        "target_companies": ["Navi", "InMobi", "Zomato"],
        "locations": [],       # intentionally open -- initial preference, not a hard rule
        "remote_ok": True,
        "min_salary": None,
        "seniority": ["entry-level", "new-grad", "associate"],
        "keywords_boost": [
            "product strategy", "analytics", "experimentation", "A/B testing", "AI",
            "marketplace", "growth", "data-driven", "fintech",
        ],
        "keywords_exclude": ["unpaid", "commission only"],
        "ranking_weights": {
            "title_match": 0.35, "company_match": 0.20, "location_match": 0.15,
            "keyword_boost": 0.15, "recency": 0.15,
        },
    },
    "sources": {
        "enabled": ["sample_board_a", "sample_board_b"],
        # Verified live on 2026-10-20: InMobi has a real public Greenhouse
        # board with current PM/Product Analyst openings in Bangalore.
        # Navi and Zomato didn't match common board-token/company-slug
        # guesses on Greenhouse or Lever -- add real tokens here once you
        # find them (check Settings -> Sources for how to verify one).
        "greenhouse_boards": ["inmobi"],
        "lever_companies": [],
    },
    "email": {
        "provider": "mock",
        "from_name": "Abhey Garg",
        "from_email": "",
    },
    "execution": {
        "mode": "approval_required",
        "paused": False,
        "per_run_limits": {"applications": 5, "emails": 5},
        "weekly_limits": {"applications": 10, "emails": 10},
        "rules_based": {"allowed_auto_email_sources": [], "allowed_auto_submit_sources": []},
    },
    "schedule": {
        "enabled": True,
        "days": ["mon", "wed", "fri"],
        "time": "08:00",
        "timezone": "Asia/Kolkata",
    },
    "notifications": {
        # Best-effort only, and only if email.provider is a real (non-mock)
        # provider -- a run summary is never required to complete a run.
        "enabled": False,
        "notify_email": "",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@dataclass
class Settings:
    raw: dict

    @property
    def profile(self) -> dict:
        return self.raw["profile"]

    @property
    def preferences(self) -> dict:
        return self.raw["preferences"]

    @property
    def sources(self) -> dict:
        return self.raw["sources"]

    @property
    def email(self) -> dict:
        return self.raw["email"]

    @property
    def execution(self) -> dict:
        return self.raw["execution"]

    @property
    def schedule(self) -> dict:
        return self.raw["schedule"]

    @property
    def notifications(self) -> dict:
        return self.raw["notifications"]

    @property
    def mode(self) -> str:
        mode = self.execution.get("mode", "approval_required")
        if mode not in VALID_MODES:
            raise ValueError(f"Invalid execution.mode '{mode}'. Must be one of {VALID_MODES}")
        return mode

    @property
    def paused(self) -> bool:
        return bool(self.execution.get("paused", False))

    def resolve_env_secret(self, env_var_name: str | None) -> str | None:
        if not env_var_name:
            return None
        return os.environ.get(env_var_name)


def load_settings(db) -> Settings:
    raw = copy.deepcopy(DEFAULT_SETTINGS)
    for section in SETTINGS_SECTIONS:
        stored = db.get_state(f"settings:{section}")
        if stored:
            raw[section] = _deep_merge(raw[section], json.loads(stored))
    return Settings(raw=raw)


def save_settings_section(db, section: str, value: dict):
    assert section in SETTINGS_SECTIONS, f"Unknown settings section '{section}'"
    db.set_state(f"settings:{section}", json.dumps(value))
