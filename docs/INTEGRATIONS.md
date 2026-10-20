# Integrations status

Reviewed October 2026 against each vendor's public documentation.
ContactOut has since been live-tested against a real (trial-tier) key --
see below for what that confirmed and what it didn't. SignalHire and
Gmail remain untested: built against documented request/response shapes,
never exercised against a real account.

## ContactOut

- **Docs reviewed:** https://api.contactout.com/ (public docs), plus the
  `contactout.com/mcp` and `contactout.com/ai-info` pages.
- **Auth:** API key in a `token:` header. There is no self-serve signup for
  the API -- a key is obtained by booking a meeting with ContactOut's team.
- **MCP integration:** `contactout.com/mcp` returned HTTP 405 to a direct
  fetch and is clearly a marketing/JS-rendered page; `ai-info` (their
  LLM-facing info page) does not describe an MCP server at all. Independent
  web search found third-party mentions of "a hosted MCP server," but
  nothing authoritative about its tool names, auth, or setup. **This was
  not implemented** -- it would require confirming real details with
  ContactOut directly, which this task was not able to do.
- **Capabilities used by `app/contacts/contactout_provider.py`:**
  - `POST /v1/people/search` -- find a person by name/company/title
- **Credits:** per-action (1 credit per profile returned, 1 per email
  found). No documented endpoint for checking remaining balance; the
  provider's `usage_info()` says to check the ContactOut dashboard directly.
- **Status: LIVE-VERIFIED on 2026-10-20, trial-tier key, sample data only.**
  A real call against a real (but trial-tier) `CONTACTOUT_API_KEY` succeeded
  and confirmed the auth header, endpoint, and response parsing are all
  correct -- two assumptions from the docs were wrong and have been fixed:
  `profiles` is a dict keyed by LinkedIn URL (not a list), and email/phone/
  verification live under each profile's `contact_info` object, not
  top-level `work_email`/`personal_email` fields.
  **However**, the response body itself said *"This is a sample response.
  To unlock full access, please book a call with our sales team"* and
  returned placeholder data (`test@gmail.com`, `email1@example.com`,
  `+123456789`, a literal `"Verified | Unverified"` status string) --
  this key proves the integration's plumbing works, not that real lookups
  work. A paid ContactOut plan is required to verify that, and hasn't been
  tested. The `/v1/people/linkedin/work_email_status` endpoint for
  standalone verification was not independently retested (the search
  response already embeds verification status, so the pipeline never
  calls it) -- treat that one method as still docs-only/unverified.

## SignalHire

- **Docs reviewed:** https://www.signalhire.com/ and
  https://docs.signalhire.com/person-api/retrieve-person.
- **Auth:** API key in an `apikey:` header.
- **Capability used by `app/contacts/signalhire_provider.py`:**
  - `POST https://www.signalhire.com/api/v1/candidate/search` -- the
    documented Person API resolves a LinkedIn URL / email / phone / UID to
    a full profile including contacts. It does **not** take a free-text
    name+company+title search -- that's a separate Search API this task
    did not find full documentation for. Because of that, `search_person()`
    only works today when a LinkedIn URL is already known (e.g. supplied
    directly by the user for a specific posting); otherwise it returns
    `None` rather than guessing at an undocumented endpoint shape.
  - Supports both async (`callbackUrl`) and sync (`withoutWaterfall: true`)
    modes; this provider uses the sync mode to fit the pipeline's simple
    call/response flow.
- **Credits:** returned via the `X-Credits-Left` response header, one
  credit per successful match.
- **Status: built, untested.** Set `SIGNALHIRE_API_KEY`, switch the
  provider to SignalHire from the dashboard's **Providers** page, then
  test with one known LinkedIn URL before enabling it for normal runs.

## Why neither is enabled by default

`contacts.enabled_provider` defaults to `null` (see `app/settings.py`'s
`DEFAULT_SETTINGS`), which means every run uses `MockContactProvider`
(`app/contacts/mock_provider.py`) -- clearly-labeled, deterministic fake
emails that never claim a "verified" status. The pipeline, dashboard, and
database schema do not care which provider is active; swapping to a real
one is a one-field change on the **Providers** page, not a code change.

## Common provider interface

`app/contacts/base.py` defines the contract every provider implements:

- `is_configured()` -- are credentials present?
- `search_person(query)` -- name/company/title -> `ContactResult | None`
- `enrich_profile(linkedin_url)` -- optional, profile URL -> `ContactResult`
- `verify_email(email)` -- optional, `"valid" | "invalid" | "unknown"`
- `usage_info()` -- credits/usage, where the provider exposes it

## Email sending

- `app/email_module/mock_email_provider.py` -- the default. Records a
  "sent" message id without any real delivery.
- `app/email_module/gmail_provider.py` -- a **real implementation** of the
  Gmail REST API (`oauth2.googleapis.com/token` for refresh, then
  `gmail.googleapis.com/.../messages.send`), authenticated with an OAuth2
  refresh token. No google-api-python-client dependency -- just two
  documented REST calls via `requests`.
  **Status: built, untested** -- no Google Cloud credentials were available
  while building it, so it has never sent a real email. Setup:
  1. Create a Google Cloud project, enable the Gmail API.
  2. Create an OAuth 2.0 Client ID (Desktop app type is simplest).
  3. Complete the OAuth consent flow once with the `https://www.googleapis.com/auth/gmail.send`
     scope (e.g. via Google's OAuth Playground) to obtain a refresh token.
  4. Set `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` as
     env vars / platform secrets, and switch email provider to Gmail from
     the dashboard's **Providers** page.
  5. Send one real test email and confirm it arrives before relying on it
     in `approval_required` or `rules_based` mode.
- Outlook has no provider class yet -- would need an Azure AD app
  registration and the Microsoft Graph `sendMail` endpoint; same
  "build it, then test it with real credentials before trusting it" rule
  applies.

## Application submission

There is no automated ATS/job-site submission adapter in this build.
`execution.rules_based.allowed_auto_submit_sources` is empty by design --
rules-based auto-submission requires a site-specific adapter that has been
checked against that site's terms of service, and none has been built or
authorized yet. Today, "approving" an application in any mode marks it
`approved` and expects you to submit it manually using the generated
package, then record it with `python -m app submit-application <id>`.
