# Job Search Agent

A persistent, repeatable job-search pipeline for Abhey Garg: discover and
import postings, dedupe and rank them against configured preferences,
identify a recruiter/hiring contact from verifiable evidence (never a
guess), prepare a tailored application package, draft a personalized
outreach message, and execute only what the configured approval mode
allows. Built to run 2-3x/week unattended in the cloud, with a dashboard
to review and control everything, and to resume cleanly if interrupted.

**No paid contact-enrichment provider is used.** ContactOut and
SignalHire were removed by explicit request -- see `docs/INTEGRATIONS.md`
for what that means and why.

**Current state:** fully functional locally (SQLite) and cloud-ready
(Postgres via the same code path, SQLAlchemy-backed). Not yet actually
deployed -- see `docs/DEPLOYMENT.md` for the exact remaining steps, which
need your own cloud account login and go-ahead on cost.

## Project structure

```
app/
  settings.py             # DB-backed profile/preferences/execution/schedule config
  db.py                    # SQLAlchemy persistence -- same code, SQLite (local) or Postgres (prod)
  resume_store.py          # resume ingestion (PDF/txt) + text extraction, stored in the DB
  models.py                # JobPosting / ContactResult / etc. data containers
  linkedin_search.py       # builds a LinkedIn Jobs search URL from keyword+filters -- no scraping
  import_jobs.py           # manual job import (single paste or CSV) -> same pipeline as discovery
  dedup.py                 # cross-source duplicate detection (discovered AND imported jobs)
  ranking.py               # configurable scoring
  recruiter_matching.py    # evidence-based recruiter/hiring-contact identification
  application_prep.py      # tailored resume + application package generation
  pipeline.py              # Runner: orchestrates one full `run`, resumable stage by stage
  actions.py               # approve/reject/pause/resume (human-in-the-loop)
  schedule_utils.py        # days/time/timezone -> UTC cron expression + APScheduler trigger
  cli.py                   # `python -m app <command>`
  sources/                 # job discovery adapters: sample (test), Greenhouse, Lever -- all free/public
  contacts/                # contact-resolution interface + mock (demo-data only, see below)
  email_module/            # email drafting + sending providers: mock, real Gmail (REST)
  dashboard/               # Flask app: discover, import, review, approve, run, pause, edit all settings
wsgi.py                    # production entrypoint: `gunicorn wsgi:app`
Procfile                   # `web: gunicorn wsgi:app`
render.yaml                # Render Blueprint (Postgres + web service)
.env.example                # every env var / secret the app reads, with placeholders
tests/                      # dedup, ranking, pipeline, import/dedup, LinkedIn-link, Greenhouse/Lever tests
docs/
  INTEGRATIONS.md           # contact-resolution policy, free-source verification, Gmail setup
  DEPLOYMENT.md             # Render/Railway architecture decision, costs, exact deploy steps
```

## Setup

```bash
cd /Users/abheygarg05/Desktop/Abhey
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in what you have; everything else stays mocked
```

No database setup is required to start: with `DATABASE_URL` unset, every
command uses a local SQLite file at `data/app.db`. Profile, preferences,
target companies/roles, execution mode, schedule, and discovery sources
are **not** config files -- they're stored in the database itself (seeded
with Abhey's real profile and PM-role preferences as defaults) and
editable from the dashboard, so nothing about you is hardcoded into the
business logic.

## Running it

```bash
# Import your resume once (or do it from the dashboard's Profile page)
python -m app import-resume AbheyGarg.pdf

# One full discovery-through-execution pass (the main command, run 2-3x/week)
python -m app run

# Re-score every active job against your current preferences (after editing them)
python -m app rerank

# Quick status line
python -m app status

# Local dashboard
python -m app dashboard
# -> http://127.0.0.1:8765 (or http://localhost:8765), default dev login admin/changeme
#    (set DASHBOARD_USERNAME/DASHBOARD_PASSWORD env vars to change this)

# Human-in-the-loop decisions (also available as buttons in the dashboard)
python -m app approve-email <id>
python -m app reject-email <id> --note "not a fit"
python -m app approve-application <id>
python -m app submit-application <id>       # after you manually submit it somewhere
python -m app reject-application <id>

# Immediately stop all external actions
python -m app pause
python -m app resume

# Optional: a local, timezone-aware recurring scheduler (for a machine/VM
# with no platform cron). Not needed on Render/Railway, which trigger
# `python -m app run` directly on their own cron.
python -m app scheduler
```

**The LinkedIn-assisted workflow runs entirely through the dashboard:**
1. `/discover` -- enter a keyword/role and filters, get a LinkedIn Jobs
   search link, open it in your own browser (nothing here touches
   LinkedIn itself).
2. Find something worth pursuing, then `/import` -- paste its URL and
   details (and recruiter info only if you actually have it). It's
   processed through the exact same pipeline as an auto-discovered job --
   deduped, ranked, matched, a tailored resume and message draft
   generated -- immediately, not on the next scheduled run.
3. `/jobs` shows everything (tagged IMPORTED or AUTO-DISCOVERED), with an
   Open Job button, a checklist for Easy Apply listings, and a copyable
   message draft when there's no email to send to directly.

In production (Render/Railway), the dashboard runs via `gunicorn wsgi:app`
(see `Procfile`/`render.yaml`) and the scheduled run is the platform's own
Cron Job service calling `python -m app run` directly -- see
`docs/DEPLOYMENT.md`.

## Demonstrated so far

```bash
.venv/bin/python -m pytest -q    # dedup, ranking, full pipeline, resumability, pause/approve,
                                   # resume ingestion, LinkedIn link-building, manual import,
                                   # import-vs-discovery dedup, Greenhouse/Lever parsing (all passing)
.venv/bin/python -m app import-resume AbheyGarg.pdf
.venv/bin/python -m app run       # run 1, then run 2: 0 new jobs/duplicates/drafts -- resumable
.venv/bin/python -m app dashboard # auth-gated, every new page tested live over HTTP
```

**Verified live against the real internet (not just unit-tested):**
- Greenhouse's public Job Board API: real call to `inmobi`'s board
  returned current openings including "Product Analyst II" and "Product
  Manager - Programmatic Monetization" in Bangalore -- genuinely useful
  for one of Abhey's three target companies, pre-configured by default.
- Lever's public Postings API: confirmed working (200 for real company
  slugs, 404 for invalid ones); none of the three target companies
  matched a common slug guess, so none is pre-configured.
- Navi and Zomato did not match common Greenhouse/Lever tokens -- they
  likely use a different ATS; add a real token in `/sources` if you find one.

One run against the bundled sample data (clearly `is_sample=True`, shaped
around Abhey's real target roles/companies) still demonstrates the full
pipeline end-to-end, including the recruiter-evidence tiers and keyword
exclusion -- see the previous session's results, unchanged by this round
of work except that contact resolution for sample data now goes through
an explicitly demo-only code path (real jobs never touch it).

## What's real vs. mocked right now

| Component | Status |
|---|---|
| Database, dedup, ranking, recruiter-evidence logic, pipeline orchestration, resumability, approval modes, dashboard incl. auth and all settings editing, resume ingestion | **Real, working, tested** |
| LinkedIn-assisted discovery | **Real, by design human-assisted.** Generates real search links from LinkedIn's own public parameters; no scraping/automation exists or is planned. |
| Manual job import (single + CSV) | **Real, tested**, including dedup against auto-discovered jobs with a different source/URL. |
| Greenhouse / Lever discovery | **Real, live-verified.** InMobi's Greenhouse board is enabled by default; add more verified tokens in `/sources`. |
| Contact lookup | **No paid provider exists.** Contact info comes only from posting evidence, info you provide at import time, or an official careers email -- never guessed, never auto-looked-up for a real job. |
| Email sending | **Mocked by default.** A real Gmail REST API provider exists (OAuth refresh-token flow) but is untested -- no Google Cloud credentials were available. |
| Application submission | **Not implemented**, including LinkedIn Easy Apply -- no automation of a logged-in interface exists or is planned. Approving marks `approved`; you submit manually and record it. |
| Cloud deployment | **Not yet deployed.** Code, manifests, and local tests are all in place; actual provisioning needs your cloud account login and cost go-ahead -- see `docs/DEPLOYMENT.md`. |

## Configuration -- all editable from the dashboard, nothing hardcoded

- **Discover** (`/discover`): LinkedIn keyword + filter search-link builder.
- **Import a job** (`/import`): paste one listing, or upload a CSV of several.
- **Sources** (`/sources`): Greenhouse board tokens / Lever company slugs to poll automatically.
- **Profile** (`/profile`): name, contact info, headline, summary, skills, links, resume upload.
- **Preferences** (`/preferences`): target roles/companies, locations, seniority, boosted/excluded
  keywords, ranking weights.
- **Providers** (`/providers`): email provider (mock/Gmail) and the contact-resolution policy note.
- **Execution** (`/execution`): research_only / approval_required (default) / rules_based, per-run
  and weekly limits, rules-based auto-action allowlists, pause.
- **Schedule** (`/schedule`): days/time/timezone (defaults to Mon/Wed/Fri 08:00 Asia/Kolkata), with
  the exact UTC cron expression to paste into Render/Railway shown live.

## Next steps

1. Try the LinkedIn-assisted workflow: `/discover` a role, open a listing in your browser,
   `/import` one you like, and see it flow through ranking/matching/drafting on `/jobs`.
2. Check `/sources` -- add a Navi or Zomato token if you find one on Greenhouse or Lever.
3. Decide Render vs. Railway (recommendation: Render) and walk through `docs/DEPLOYMENT.md` --
   I'll need your login to actually create the account/Postgres/services, and your explicit
   go-ahead once you see the real cost screen.
4. If you want real email sending, set up the Gmail OAuth app and send one real test email before
   trusting it in `approval_required` mode.
