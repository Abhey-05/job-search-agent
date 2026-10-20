"""No paid contact-enrichment provider is used by this application --
ContactOut and SignalHire were removed per an explicit decision not to pay
for or depend on a contact-data vendor (see docs/INTEGRATIONS.md).

Recruiter contact info now comes only from:
  1. Evidence already present on the job posting (a named recruiter's
     email, if the source happens to supply one -- see app/recruiter_matching.py).
  2. Information the user explicitly provides at import time (the
     dashboard's manual-import form has optional recruiter name/email/
     LinkedIn-profile fields).
  3. An official company careers-contact email found on the listing.

`MockContactProvider` is kept only for sample/demo data (`is_sample=True`
jobs) so the pipeline and dashboard remain demonstrable without any real
job imported yet -- see app/pipeline.py's lookup_contacts, which never
calls it for a real (non-sample) job. This function exists so that
interface stays swappable if a free/permitted provider is ever added
later; it intentionally never returns anything that calls a paid API.
"""
from __future__ import annotations

from app.contacts.base import ContactProvider
from app.contacts.mock_provider import MockContactProvider


def get_sample_demo_provider() -> ContactProvider:
    return MockContactProvider()
