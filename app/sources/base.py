"""Source adapter contract.

A source adapter's only job is to return a list of JobPosting objects. It
knows nothing about ranking, dedup, contacts, or the database -- that
separation is what makes sources interchangeable: adding a new job board
means writing one class and registering it, nothing else changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import JobPosting


class JobSource(ABC):
    name: str = "unnamed_source"

    @abstractmethod
    def fetch(self, config) -> list[JobPosting]:
        """Return the current set of postings visible to this source.

        Implementations must only use discovery methods permitted by the
        source's terms of service (e.g. a public API or RSS feed). Scraping
        a site that prohibits it, or automating a platform's restricted
        actions, is out of scope for this method.
        """
        raise NotImplementedError
