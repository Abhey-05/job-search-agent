# Integrations status

## Contact resolution: no paid provider, by explicit decision

ContactOut and SignalHire were removed from this app entirely (both the
API-calling code and the credentials/config for them) at the user's
explicit request not to pay for or depend on a contact-data vendor. For
the record, before removal: ContactOut was live-verified on 2026-10-20
against a real trial-tier key -- the request/auth/response-parsing all
worked, but the account only returned ContactOut's documented placeholder
"sample response" content, not real lookups (that needs a paid plan).
SignalHire was built against its public docs but never tested. Both
implementations were deleted along with this feature; they are not
present in the codebase and are not planned to come back unless a free/
permitted alternative appears.

**Recruiter contact info now comes only from:**
1. Evidence already on the job posting itself (a named recruiter/hiring
   manager, if the source happens to supply one -- `app/recruiter_matching.py`).
2. Information the user explicitly provides at import time -- the
   dashboard's `/import` form has optional recruiter name/title/email/
   LinkedIn-profile-URL fields, stored with `provider = "user_provided"`
   and `email_status = "unverified"` (never claimed "verified" without
   actual third-party verification).
3. An official company careers/talent-acquisition email found on the listing.

If none of those give an email, it is left blank. `app/pipeline.py`'s
`lookup_contacts` enforces this directly: for any job where
`is_sample == False` (i.e. every real, non-demo job), it never calls any
provider -- it only logs that no automated lookup is available. The only
place `MockContactProvider` (`app/contacts/mock_provider.py`) is still
used is for `is_sample=True` demo/test jobs, so the pipeline stays
demonstrable without requiring a single real job to be imported first.
`app/contacts/base.py`'s `ContactProvider` interface is kept in case a
genuinely free/permitted provider shows up later -- dropping one in would
be a new class + a registry entry, not a pipeline change.

## Free job discovery sources

### LinkedIn (human-assisted, no automation)

`app/linkedin_search.py` builds a LinkedIn Jobs search URL from keyword +
filters (location, date posted, experience level, employment type,
workplace type, Easy Apply) using LinkedIn's own public search-page query
parameters -- the same page and parameters you'd land on by clicking
their filter chips. The dashboard's `/discover` page shows this link for
you to open and browse in your own, logged-in browser. Nothing in this
app fetches, scrapes, parses, or authenticates against LinkedIn -- it
only ever constructs a URL. When you find something worth pursuing --
including a role mentioned in a recruiter's feed post, not just a formal
listing -- use `/import` to paste in whatever you have: the post/listing
URL, the role and company as best you can tell, and the recruiter's name
and profile URL if named. The description field accepts free text, so a
recruiter's post text works fine there too.

### MCP evaluation -- audited 2026-10-21, none recommended

Checked whether any MCP server could provide authorized LinkedIn job
search, recruiter-post reading, or messaging. Findings:

- **No official LinkedIn MCP server exists.** LinkedIn publishes no MCP
  product alongside Sign In with LinkedIn, Share on LinkedIn, the
  Community Management API, or the Advertising API -- confirmed via
  direct research, not assumed.
- **Every third-party "LinkedIn MCP server" found falls into one of two
  categories, neither of which is safe to install:**
  1. **Session/browser-automation based** (e.g. `stickerdaniel/linkedin-mcp-server`
     and its many forks). Its own README states it "controls a real
     browser session" via reused or manually-entered LinkedIn login
     cookies, and warns outright: *"LinkedIn's User Agreement prohibits
     automated access, and accounts using automated tools can be
     restricted or banned. Use at your own risk."* This is exactly the
     cookie-based/bypass category the user asked not to install.
  2. **Public scraping without login** (e.g. `administrativetrick/linkedin-mcp`,
     via the third-party `linkedin-jobs-api` package). No login needed,
     but it still scrapes LinkedIn's site to get job data, which is
     still automated access LinkedIn's terms prohibit regardless of
     whether you're logged in -- and its own README acknowledges it
     "could break if LinkedIn changes their HTML structure."
- **Conclusion: no MCP integration is recommended or installed.** Both
  categories do exactly what the official-API audit already established
  is unavailable through authorized means -- they just do it anyway, in
  a way that risks the account. The existing LinkedIn search-link +
  manual-import workflow above, plus the OAuth sign-in (profile/email
  only, see below), remain the full extent of this app's LinkedIn
  integration, by design.

LinkedIn's `f_C` company filter needs a numeric internal company ID that
isn't resolvable without LinkedIn API/scraping access, so "target
company" in the discover form is folded into the keyword text instead --
a bias, not a strict filter.

### LinkedIn OAuth / Sign-In -- audited 2026-10-21, built, UNTESTED

**What's actually available.** Reviewed LinkedIn's official developer
docs (learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access
and the OpenID Connect / 3-legged OAuth pages). LinkedIn's API access is
split into Open Permissions (self-serve, no approval) and everything
else (requires a formal partner application):

| Tier | Products | Approval needed? |
|---|---|---|
| Open (self-serve) | Sign in with LinkedIn using OpenID Connect (`openid`, `profile`, `email`); Share on LinkedIn (`w_member_social`) | No |
| Talent Solutions | Recruiter System Connect, Apply Connect, Apply with LinkedIn, Premium Job Posting | Yes -- formal ATS-partner application, business-to-business, not available to an individual developer |
| Marketing / Sales | Advertising API, Sales Navigator (SNAP) | Yes -- partner approval |
| Compliance | r_compliance, w_compliance | Closed, not requestable |

**Conclusion: job search, job-posting data, messaging, and Easy Apply
are not available through self-serve LinkedIn API access at all** --
they all live under Talent Solutions, gated behind a partner program
this app (and an individual developer) cannot apply to. This was
assumed going in and the official docs confirm it; nothing was skipped
or missed.

**What is available and genuinely useful:** "Sign in with LinkedIn using
OpenID Connect" -- `openid profile email` scope, self-serve, auto-granted
on creating a Developer app. It returns the member's name, email, and
profile picture. Nothing else. `w_member_social` (posting/commenting on
the member's feed) was deliberately NOT requested -- it doesn't serve a
private job-search/outreach use case and would be an unused, unnecessary
permission to hold.

**Implementation** (`app/linkedin_oauth.py`, routes in
`app/dashboard/server.py` under `/auth/linkedin/*`): the standard 3-legged
OAuth 2.0 authorization-code flow against LinkedIn's real, documented
endpoints --
  - `GET https://www.linkedin.com/oauth/v2/authorization` (redirect the user here)
  - `POST https://www.linkedin.com/oauth/v2/accessToken` (exchange code for token)
  - `GET https://api.linkedin.com/v2/userinfo` (fetch name/email)

Security properties: a random CSRF `state` value is generated per
connect attempt, stored server-side (DB `app_state`, not a cookie --
robust across multiple gunicorn workers), and consumed exactly once on
callback (`Database.pop_oauth_state`) -- a mismatched or replayed state
is rejected with 401. The access token is stored in the app's own
database (not logged, not rendered in any template -- only derived
display fields like name/email/expiry ever reach a page), scoped to
`openid profile email` only. A **Disconnect** button on `/profile`
deletes the stored token immediately. LinkedIn has no token-revocation
endpoint in the open-permissions tier, so disconnect means "this app
forgets its copy," not "LinkedIn is notified" -- the UI says this
explicitly rather than implying otherwise.

**Feature flag:** entirely inert unless `LINKEDIN_CLIENT_ID`,
`LINKEDIN_CLIENT_SECRET`, and `LINKEDIN_REDIRECT_URI` are all set --
`linkedin_oauth.is_configured()` gates every route, and `/profile` shows
"Not configured" with no button at all otherwise.

**Status: built against official docs, never exercised against a real
LinkedIn Developer app** -- no credentials were available while building
it. Nowhere in this app does it say "LinkedIn connected" unless a real
OAuth callback has actually completed; `/profile` reflects the real
stored state, not an assumption.

**Setup steps (yours to do -- these need your LinkedIn account):**
1. Go to https://www.linkedin.com/developers/apps and create a new app.
   LinkedIn's Developer Portal has historically required linking a new
   app to a LinkedIn Company Page -- if prompted, you can create a
   minimal one under your own name to satisfy this; it doesn't need to
   be a real business.
2. In the app's **Products** tab, add "Sign In with LinkedIn using
   OpenID Connect" -- this is immediate/self-serve, no review wait.
3. In the app's **Auth** tab, add your redirect URL, e.g.
   `https://<your-render-service>.onrender.com/auth/linkedin/callback`
   (or `http://localhost:8765/auth/linkedin/callback` for local testing).
   It must be an exact, absolute HTTPS URL with no query string or `#`.
4. Copy the Client ID and Client Secret from the Auth tab.
5. Set `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, and
   `LINKEDIN_REDIRECT_URI` (matching step 3 exactly) as env vars /
   platform secrets -- **do not paste these values into chat**; set them
   directly in `.env` (gitignored) or the platform's secret store.
6. Visit `/profile`, click **Connect LinkedIn**, approve the consent
   screen, and confirm it shows your real name/email back. That's the
   only way this gets marked "working" rather than "built, untested."

### Greenhouse (public Job Board API) -- LIVE-VERIFIED 2026-10-20

`GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true`
is Greenhouse's own public, unauthenticated API, built for exactly this
kind of consumption. Verified with two real calls:
- `stripe` board: HTTP 200, 725 real postings, confirms the schema `app/sources/greenhouse_source.py` assumes.
- `inmobi` board: HTTP 200, real current openings including "Product
  Analyst II" and "Product Manager - Programmatic Monetization" in
  Bangalore -- genuinely useful for the user's actual target companies.

Not every company has a Greenhouse board, and the token isn't always
guessable: `navi`, `navitechnologies`, and `zomato` all returned 404.
Configure real, verified tokens in the dashboard's `/sources` page; the
default ships with `inmobi` pre-added since it's confirmed working.

### Lever (public Postings API) -- LIVE-VERIFIED 2026-10-20

`GET https://api.lever.co/v0/postings/{company}?mode=json` is Lever's own
public, unauthenticated API. Verified: `palantir` returned HTTP 200 with
real posting content; made-up slugs (`ramp`, `eventbrite`) returned 404.
None of the user's three target companies matched a common Lever slug
guess. No company is pre-configured by default; add a verified one in
`/sources`.

### What's NOT included, and why

Generic company-career-page scraping is not implemented. Each site has
its own markup, structure, and terms of use -- a generic scraper would be
unreliable at best and could violate a specific site's terms at worst.
If a specific company exposes its own public, documented job-listing API
(not Greenhouse/Lever), a dedicated adapter can be built and verified the
same way these two were -- real call, real response, documented before
being trusted.

## Email sending

- `app/email_module/mock_email_provider.py` -- the default. Records a
  "sent" message id without any real delivery. Drafts are generated
  regardless of which provider is active -- Gmail credentials are never
  required just to draft a message.
- `app/email_module/gmail_provider.py` -- a real implementation of the
  Gmail REST API (OAuth2 refresh-token flow, two documented REST calls,
  no extra client library). **Status: built, untested** -- no Google
  Cloud credentials were available while building it. Setup:
  1. Create a Google Cloud project, enable the Gmail API.
  2. Create an OAuth 2.0 Client ID (Desktop app type is simplest).
  3. Complete the OAuth consent flow once with the
     `https://www.googleapis.com/auth/gmail.send` scope (e.g. via
     Google's OAuth Playground) to obtain a refresh token.
  4. Set `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`
     as env vars / platform secrets, and switch the email provider to
     Gmail from the dashboard's **Providers** page.
  5. Send one real test email and confirm it arrives before relying on
     it in `approval_required` or `rules_based` mode.
- Sending (not drafting) is always approval-gated regardless of provider
  -- see `app/actions.py`'s `approve_email` and `app/pipeline.py`'s
  `build_and_execute_queue`.

## Application submission

There is no automated ATS/job-site submission adapter in this build, for
LinkedIn Easy Apply or anything else -- that would require automating a
logged-in interface, which this app explicitly does not do. "Approving"
an application marks it `approved` and expects you to complete submission
yourself (through LinkedIn's own interface, or wherever the listing
points), then record it with `python -m app submit-application <id>` or
the dashboard's "mark as manually submitted" button.
