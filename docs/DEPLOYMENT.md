# Cloud deployment

## Architecture decision

**Recommendation: Render**, with Railway documented as an alternative.
Both were evaluated against: scheduled/cron jobs, managed Postgres, private
storage, secrets management, logs/monitoring, and deploy simplicity.

| | Render | Railway |
|---|---|---|
| Background worker / cron | Native `type: cron` Blueprint resource with a direct `schedule` field -- confirmed against Render's official Blueprint spec (render.com/docs/blueprint-spec) and now included in `render.yaml`. Billed per execution-minute, on the order of ~$1/mo for a few-minutes-a-week job. | Native cron via a service's "Cron Schedule" setting (dashboard-only, not Blueprint-equivalent). Same per-service model; billed from the usage-metered plan. |
| Managed Postgres | $0 for 30 days, then $6/mo (256MB) minimum, capped at 1GB on that tier. 14-day grace period after the 30 days before deletion. | Usage-metered as part of the plan; no separate flat Postgres price publicly fixed -- draws from the Hobby plan's included $5 usage. |
| Web dashboard | Free tier: 750 hrs/mo, sleeps after 15 min idle (~1 min cold start), no disk. Fine for a personal, occasionally-used dashboard. | No perpetual free tier; Hobby plan is $5/mo minimum (includes $5 of usage). |
| Pricing model | Flat, itemized -- easy to predict. | Usage-metered (GB-RAM-hour + vCPU-hour) -- cheaper for very light use, harder to predict exactly. |
| Deploy mechanism | `render.yaml` Blueprint (included in this repo) from a connected GitHub repo, or manual dashboard setup. | CLI-first (`railway up` from local dir, no GitHub required) or GitHub-connected. |
| **Estimated total** | **~$7/month** (free web + $6 Postgres + ~$1 cron) after the first 30 days. | **~$5/month** floor (Hobby plan), could run higher if usage exceeds the included $5. |

Both only accept **UTC cron expressions with no DST awareness** for their
cron job schedule field -- `app/schedule_utils.py` computes the UTC
equivalent of your Asia/Kolkata schedule for you (shown on the dashboard's
`/schedule` page), and since IST has no DST this conversion is exact and
permanent.

**Nothing gets created in either platform until you say so.** This repo is
ready to deploy (render.yaml, Procfile, wsgi.py, requirements.txt all in
place and tested locally against SQLite) but creating the actual account,
Postgres instance, and services is a step only you can take (it needs your
login), and the $6-7/month Postgres cost only starts once you do.

## Deploying to Render (recommended path)

The repo is already on GitHub at **github.com/Abhey-05/job-search-agent**
(private), up to date with everything described in this document --
step 1 from an earlier draft of this doc (push to GitHub) is done.

1. **Create a Render account** at render.com (needs your login -- I can't
   do this step for you).

2. In the Render dashboard: **New +** -> **Blueprint**, select the
   `job-search-agent` repo. Render reads `render.yaml` and shows you
   exactly what it will create -- one Postgres database, one web service,
   **and one cron job** (all three are now in the Blueprint; an earlier
   version of this file had you create the cron job manually because an
   unofficial source suggested Render's Blueprint cron support wasn't
   confirmed -- it is, per Render's own spec, and `render.yaml` reflects
   that now) -- and the cost for each, **before** creating anything.
   Review and approve that screen yourself.

3. After the Blueprint applies, set the secret env vars it left blank
   (`sync: false` in render.yaml) on **both** the web service and the
   cron job (they need the same `DATABASE_URL` to share one database --
   the Blueprint wires that automatically via `fromDatabase`, so you only
   need to set the non-database secrets): `DASHBOARD_USERNAME`,
   `DASHBOARD_PASSWORD`, `FLASK_SECRET_KEY` (web only -- the cron job
   doesn't serve HTTP, so it doesn't need these), and optionally
   `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` / `GMAIL_REFRESH_TOKEN` and
   `LINKEDIN_CLIENT_ID` / `LINKEDIN_CLIENT_SECRET` / `LINKEDIN_REDIRECT_URI`
   on whichever services need them (Gmail: both; LinkedIn sign-in: web only,
   since it's a dashboard feature). No contact-provider keys exist to set;
   see docs/INTEGRATIONS.md for why.

4. Visit your web service's URL, log in with `DASHBOARD_USERNAME`/
   `DASHBOARD_PASSWORD`, confirm the dashboard loads, then trigger **Run
   now** once manually to smoke-test the whole pipeline against the real
   deployment before waiting for the first scheduled cron run.

5. Double-check the cron job's schedule field in the Render dashboard
   matches what's in `render.yaml` (`30 2 * * 1,3,5`, i.e. Mon/Wed/Fri
   08:00 Asia/Kolkata) and matches what the dashboard's `/schedule` page
   currently shows -- if you've changed the schedule there since this was
   written, update both `render.yaml` and the live cron job's schedule
   field and redeploy; it is not read dynamically from the app's database.

## Deploying to Railway (alternative)

```bash
npm install -g @railway/cli   # or follow railway.app/cli
railway login                 # opens a browser; needs your account
railway init                  # creates a new Railway project
railway add                   # choose "Postgres" from the plugin list
railway up                    # deploys this repo as a service
railway variables set DASHBOARD_USERNAME=... DASHBOARD_PASSWORD=... FLASK_SECRET_KEY=...
railway variables set DATABASE_URL=$(railway variables get DATABASE_URL --service postgres)
```

Then in the Railway dashboard, create a **second service** from the same
repo for the scheduled run: set its start command to `python -m app run`,
and set its "Cron Schedule" field to the UTC cron expression from your
dashboard's `/schedule` page. Give it the same `DATABASE_URL` as the web
service so they share one database.

## What you need to decide/provide before either deploy actually happens

- Which platform (Render recommended, both fully supported by this repo).
- Your own login to that platform (I cannot create or log into a cloud
  account on your behalf).
- Explicit go-ahead once you've seen the real cost screen that platform
  shows you -- I will not click "create" on anything paid for you.
- `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD` -- pick a real password, not
  the local dev default (`admin`/`changeme`); the app refuses to start
  with that default when `FLASK_ENV=production` (which both render.yaml
  and a typical Railway deploy set).
- Optionally: Gmail OAuth credentials, if you want real sending instead
  of mock -- the app runs fully functional with drafting-only otherwise.
- Optionally: LinkedIn Developer app credentials, if you want the
  profile/email autofill sign-in -- entirely optional, does not affect
  job search/import/ranking/drafting either way.
- There is no paid contact-provider to configure; see docs/INTEGRATIONS.md.

## Operational notes

- **Idempotency across redeploys**: all state (jobs, applications, email
  drafts, settings, resumes) lives in Postgres, not on the container's
  disk -- a redeploy, a dashboard restart, or the scheduled worker running
  on a totally separate container all see the same data.
- **The scheduled run is independent of the dashboard.** The Cron Job
  service runs `python -m app run`, does its work, and exits -- it doesn't
  need the web service to be awake (even on Render's free tier, where the
  web service sleeps after 15 minutes of no traffic).
- **Logs**: both platforms show per-service logs in their dashboard,
  including every `python -m app run` invocation's stdout (the JSON run
  summary) and any traceback on failure.
- **Backups**: Render's managed Postgres includes automatic daily backups
  on paid plans (not the free 30-day trial tier) -- worth confirming once
  you're on the $6/mo tier if this matters to you.
- **Immediate pause**: the dashboard's "Pause all external actions" button
  (and `python -m app pause`) takes effect on the *next* pipeline stage
  check, including mid-run on the scheduled worker, since it's a DB flag
  every run reads live.
