# Job Search Agent

A persistent, repeatable job-search pipeline for Abhey Garg: discover
postings, dedupe and rank them against configured preferences, identify a
recruiter/hiring contact, look up and verify a contact email where
authorized, prepare a tailored application package, draft a personalized
outreach email, and execute only what the configured approval mode
allows. Built to run 2-3x/week unattended in the cloud, with a dashboard
to review and control everything, and to resume cleanly if interrupted.

**Current state:** fully functional locally (SQLite) and cloud-ready
(Postgres via the same code path, SQLAlchemy-backed). Not yet actually
deployed -- see `docs/DEPLOYMENT.md` for the exact remaining steps, which
need your own cloud account login and go-ahead on cost.

## Project structure

```
app/
  settings.py           # DB-backed profile/preferences/execution/schedule config
  db.py                  # SQLAlchemy persistence -- same code, SQLite (local) or Postgres (prod)
  resume_store.py        # resume ingestion (PDF/txt) + text extraction, stored in the DB
  models.py              # JobPosting / ContactResult / etc. data containers
  dedup.py               # cross-source duplicate detection
  ranking.py             # configurable scoring
  recruiter_matching.py  # evidence-based recruiter/hiring-contact identification
  application_prep.py    # tailored resume + application package generation
  pipeline.py            # Runner: orchestrates one full `run`, resumable stage by stage
  actions.py             # approve/reject/pause/resume (human-in-the-loop)
  schedule_utils.py       # days/time/timezone -> UTC cron expression + APScheduler trigger
  cli.py                 # `python -m app <command>`
  sources/               # job discovery adapters (interchangeable)
  contacts/              # contact-lookup providers: mock, ContactOut, SignalHire (interchangeable)
  email_module/          # email drafting + sending providers: mock, real Gmail (REST)
  dashboard/             # Flask app: review, approve, run, pause, edit all settings
wsgi.py                  # production entrypoint: `gunicorn wsgi:app`
Procfile                 # `web: gunicorn wsgi:app`
render.yaml              # Render Blueprint (Postgres + web service)
.env.example             # every env var / secret the app reads, with placeholders
tests/                   # dedup, ranking, and full-pipeline integration tests
docs/
  INTEGRATIONS.md        # ContactOut/SignalHire/Gmail research + what's real vs. untested
  DEPLOYMENT.md           # Render/Railway architecture decision, costs, exact deploy steps
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
target companies/roles, execution mode, and schedule are **not** config
files -- they're stored in the database itself (seeded with Abhey's real
profile and PM-role preferences as defaults) and editable from the
dashboard, so nothing about you is hardcoded into the business logic.

## Running it

```bash
# Import your resume once (or do it from the dashboard's Profile page)
python -m app import-resume AbheyGarg.pdf

# One full discovery-through-execution pass (the main command, run 2-3x/week)
python -m app run

# Quick status line
python -m app status

# Local dashboard -- review, approve, run, pause, edit profile/preferences/schedule
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

In production (Render/Railway), the dashboard runs via `gunicorn wsgi:app`
(see `Procfile`/`render.yaml`) and the scheduled run is the platform's own
Cron Job service calling `python -m app run` directly -- see
`docs/DEPLOYMENT.md`.

## Demonstrated so far

```bash
.venv/bin/python -m pytest -q                      # 14 tests: dedup, ranking, full pipeline,
                                                     # resumability, pause/approve, resume ingestion
.venv/bin/python -m app import-resume AbheyGarg.pdf # real resume ingested, text extracted via pypdf
.venv/bin/python -m app run                         # run 1
.venv/bin/python -m app run                         # run 2: 0 new jobs/duplicates/drafts -- resumable
.venv/bin/python -m app dashboard                   # auth-gated (401 without creds, 200 with),
                                                     # profile/preferences/providers/schedule/execution
                                                     # pages all tested via HTTP, settings round-trip
                                                     # through a POST confirmed persisted in the DB
.venv/bin/gunicorn wsgi:app                         # production entrypoint boots and serves correctly
```

One run against the bundled sample data (two mock sources, shaped around
Abhey's real target companies -- Navi, InMobi, Zomato -- and PM roles):

- 5 postings discovered; 1 cross-source duplicate detected and linked, not re-processed
- Ranking correctly favors the two target-company postings (Navi 0.86, InMobi 0.81) over a
  non-target-company posting (0.63), and zeroes out one that matched `keywords_exclude: ["commission only"]`
- 3 jobs got a recruiter/hiring-contact match (named recruiter, hiring manager, and a
  no-name "likely team" case); the excluded job correctly got no recruiter/outreach effort at all
- 2 got a mock contact email resolved; 1 (no individual name available) correctly got none
- 3 tailored application packages generated, built from Abhey's actual uploaded resume text
  (verified: extracted name/email/phone from the real PDF appear in the generated output)
- 3 personalized recruiter emails drafted, referencing the specific job and (where known) the
  specific recruiter by name
- Nothing was sent or submitted -- `approval_required` mode (the default) queued everything for review

## What's real vs. mocked right now

| Component | Status |
|---|---|
| Database (Postgres-compatible via SQLAlchemy), dedup, ranking, recruiter-evidence logic, pipeline orchestration, resumability, approval modes, dashboard incl. auth and all settings editing, resume ingestion | **Real, working, tested** |
| Job discovery | **Mocked.** Two sample source adapters, shaped around real target companies/roles. Add a real one by implementing `JobSource` and registering it -- nothing else changes. |
| Contact lookup | **Mocked by default.** Real ContactOut and SignalHire provider classes exist (built against their public docs) but are untested -- no credentials were available. See `docs/INTEGRATIONS.md`. |
| Email sending | **Mocked by default.** A real Gmail REST API provider exists (OAuth refresh-token flow) but is untested -- no Google Cloud credentials were available. |
| Application submission | **Not implemented.** No site has an authorized auto-submit adapter. Approving an application marks it `approved`; you submit manually and record it with `submit-application`. |
| Cloud deployment | **Not yet deployed.** Code, manifests, and local tests are all in place; actual provisioning needs your cloud account login and cost go-ahead -- see `docs/DEPLOYMENT.md`. |

## Configuration -- all editable from the dashboard, nothing hardcoded

- **Profile** (`/profile`): name, contact info, headline, summary, skills, links, resume upload.
  Seeded with Abhey's confirmed details from the brief; education/experience/projects/leadership
  are editable via an advanced JSON field until a dedicated form is worth building.
- **Preferences** (`/preferences`): target roles/companies, locations, seniority, boosted/excluded
  keywords, ranking weights. Seeded with Product Manager / Technical PM / Product Analyst roles,
  Navi/InMobi/Zomato as target companies (boost, not a hard filter), per the brief.
- **Providers** (`/providers`): contact-lookup provider (mock/ContactOut/SignalHire) and email
  provider (mock/Gmail), plus live integration-health status.
- **Execution** (`/execution`): research_only / approval_required (default) / rules_based, per-run
  and weekly limits, rules-based auto-action allowlists, pause.
- **Schedule** (`/schedule`): days/time/timezone (defaults to Mon/Wed/Fri 08:00 Asia/Kolkata), with
  the exact UTC cron expression to paste into Render/Railway shown live.

## Next steps

1. Review your profile/preferences on the dashboard and adjust anything that isn't quite right
   (the summary and skills list were composed from the brief -- check they read the way you want).
2. Decide Render vs. Railway (recommendation: Render) and walk through `docs/DEPLOYMENT.md` --
   I'll need your login to actually create the account/Postgres/services, and your explicit
   go-ahead once you see the real cost screen.
3. If/when you get ContactOut or SignalHire access, set the API key and run one authorized test
   lookup (`docs/INTEGRATIONS.md` has the exact untested assumptions to verify).
4. If you want real email sending, set up the Gmail OAuth app and send one real test email before
   trusting it in `approval_required` mode.
5. Add a real job source adapter when you've picked one (a company careers API, Greenhouse, etc.).
