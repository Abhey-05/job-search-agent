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
only ever constructs a URL. When you find something worth pursuing, use
`/import` to paste it in.

LinkedIn's `f_C` company filter needs a numeric internal company ID that
isn't resolvable without LinkedIn API/scraping access, so "target
company" in the discover form is folded into the keyword text instead --
a bias, not a strict filter.

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
