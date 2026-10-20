"""Maps config -> JobSource instances.

Three kinds of sources, all modular/pluggable:
  1. Static test/demo adapters (sample_board_a/b) -- always available by name.
  2. Greenhouse boards -- one instance per board token in
     settings.sources.greenhouse_boards (each a verified-by-you company slug).
  3. Lever companies -- one instance per company slug in
     settings.sources.lever_companies.

Manually-imported jobs (LinkedIn-assisted or pasted from anywhere) are
NOT a JobSource -- they don't get "fetched" on a schedule, they're
inserted directly via app/import_jobs.py when the user submits the
dashboard's import form. They still flow through the rest of the same
pipeline (dedup, rank, recruiter match, contact, package, draft).
"""
from __future__ import annotations

from app.sources.base import JobSource
from app.sources.greenhouse_source import GreenhouseBoardSource
from app.sources.lever_source import LeverCompanySource
from app.sources.sample_source import SampleBoardA, SampleBoardB

_STATIC_REGISTRY: dict[str, type[JobSource]] = {
    "sample_board_a": SampleBoardA,
    "sample_board_b": SampleBoardB,
}


def get_enabled_sources(config) -> list[JobSource]:
    sources: list[JobSource] = []

    for name in config.sources.get("enabled", []):
        cls = _STATIC_REGISTRY.get(name)
        if cls is None:
            raise ValueError(
                f"Unknown source '{name}' in sources.enabled. "
                f"Known static sources: {sorted(_STATIC_REGISTRY)}"
            )
        sources.append(cls())

    for token in config.sources.get("greenhouse_boards", []):
        sources.append(GreenhouseBoardSource(token))

    for company in config.sources.get("lever_companies", []):
        sources.append(LeverCompanySource(company))

    return sources
