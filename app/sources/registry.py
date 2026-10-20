"""Maps config names -> JobSource implementations.

Adding a real source adapter (Greenhouse, Lever, a careers API) is: write
the class, add one line here. The pipeline and dashboard never change.
"""
from __future__ import annotations

from app.sources.base import JobSource
from app.sources.sample_source import SampleBoardA, SampleBoardB

_REGISTRY: dict[str, type[JobSource]] = {
    "sample_board_a": SampleBoardA,
    "sample_board_b": SampleBoardB,
}


def get_enabled_sources(config) -> list[JobSource]:
    enabled_names = config.sources.get("enabled", [])
    sources = []
    for name in enabled_names:
        cls = _REGISTRY.get(name)
        if cls is None:
            raise ValueError(
                f"Unknown source '{name}' in sources.enabled. "
                f"Known sources: {sorted(_REGISTRY)}"
            )
        sources.append(cls())
    return sources
