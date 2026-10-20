# Cloud deployment

## Architecture decision

**Recommendation: Render**, with Railway documented as an alternative.
Both were evaluated against: scheduled/cron jobs, managed Postgres, private
storage, secrets management, logs/monitoring, and deploy simplicity.

| | Render | Railway |
|---|---|---|
| Background worker / cron | Native Cron Job service type, billed per execution-minute ($0.00016/min + $1/mo minimum per cron service). Dashboard-configured; not confirmed to be settable via `render.yaml`. | Native cron via a service's "Cron Schedule" setting. Same per-service model; billed from the usage-metered plan. |
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

1. **Push this repo to GitHub** (Render's Blueprint flow reads from a
   connected Git repo):
   ```bash
   git init
   git add -A
   git commit -m "Initial job-search agent"
   gh repo create <your-repo-name> --private --source=. --push
   # or: create the repo on github.com and `git push` to it yourself
   ```
   Your resume PDF and `.env` are already gitignored and will not be pushed.

2. **Create a Render account** at render.com (needs your login -- I can't
   do this step for you).

3. In the Render dashboard: **New +** -> **Blueprint**, select your repo.
   Render reads `render.yaml` and shows you exactly what it will create
   (one Postgres database, one web service) and its cost **before**
   creating anything -- review and approve that screen yourself.

4. After the Blueprint applies, set the secret env vars it left blank
   (`sync: false` in render.yaml) in the web service's **Environment** tab:
   `DASHBOARD_USERNAME`, `DASHBOARD_PASSWORD`, `FLASK_SECRET_KEY`, and --
   only if you've set up Gmail sending -- `GMAIL_CLIENT_ID` /
   `GMAIL_CLIENT_SECRET` / `GMAIL_REFRESH_TOKEN`. No contact-provider keys
   exist to set; see docs/INTEGRATIONS.md for why.

5. **Create the scheduled run** as a separate Cron Job service (New + ->
   Cron Job), same repo:
   - Command: `python -m app run`
   - Schedule: the UTC cron expression shown on your dashboard's
     `/schedule` page (defaults to `30 2 * * 1,3,5` = Mon/Wed/Fri 08:00 IST)
   - Same env vars as the web service (especially `DATABASE_URL` -- copy
     the same Postgres connection string so both services share one database)

6. Visit your web service's URL, log in with `DASHBOARD_USERNAME`/
   `DASHBOARD_PASSWORD`, confirm the dashboard loads, then trigger **Run
   now** once manually to smoke-test the whole pipeline against the real
   deployment before waiting for the first scheduled run.

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
  There is no paid contact-provider to configure; see docs/INTEGRATIONS.md.

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
