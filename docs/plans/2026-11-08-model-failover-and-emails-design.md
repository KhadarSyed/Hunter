# Model failover, outage alerts and one email design

Date: 2026-11-08 · Status: approved in conversation (sections 1–2; section 3 below)

## Goal

1. A project running on an organisation's own models survives a provider outage: it moves to the org's next working
   model, or waits until one answers, and never touches the platform GPT-5 (only InfoVision runs on that).
2. The org's Admins are emailed when an outage starts (switched or paused) and when it ends, with the affected
   projects (name, client logo, stage) and every model's state (provider logo, reason).
3. Every email the app sends uses one AlphaMetricx design, in a fixed lifecycle: account created → verification code
   → reset link → Matching label ready → data set tagged → stage stopped → outage switched → outage paused →
   recovered → deliverable ready.

## Outage handling

- **Outage**: HTTP 5xx, 429 after retries, timeouts, dropped connections, an error inside a stream. **Config fault**:
  401/403/404 — handled the same way, the email says to fix the key or model. **Not an outage**: a cut-off reply,
  bad JSON or HTTP 400 — unchanged (tagging re-packs; the caller sees the error).
- **Order**: the org's saved default, then its other providers newest first. A provider that fails is marked down for
  2 minutes; the next call skips it and uses the next healthy one (the acting default). When the saved default
  answers a health check again, calls go back to it. The saved default never changes on its own.
- **All down**: the call waits instead of failing: it rechecks the org's models every 5 minutes and continues the
  moment one answers, so a project resumes exactly where it stopped (mid-tagging, mid-deck). After 12 hours it gives
  up with a clear error. Pages show "Paused · waiting for a model" for the org's running stages meanwhile.
  Known limit: Background Research and Search Strategy keep their own time limits, so a long outage still finishes
  those two with rule-based content, as an Azure outage does today.
- **State**: table `org_llm_state` (migration 49): org, acting provider, down since, failed calls, last email sent
  (switched / paused). One row per org in an outage; cleared on recovery.
- **Emails**: to every Admin of the org, once per event: switched, paused (also after a switch), recovered.
  Never repeated while the state is unchanged.

## Emails

- One layout (`core/templates/email.html.j2`, `core/email_layout.py`), Outlook-safe tables: the AlphaMetricx wordmark
  (S3 `HunterAgent/assets/house/alphametricx-logo.png`, embedded at up to 3x), a status pill, heading, intro,
  callout, code box, facts, button, models list (provider logos), projects list (client logos), an Organization panel
  (organization, each admin's name and email, active projects) and the footer:
  "Questions? support@alphametricx.com · AlphaMetricx © <current year> · Never share your password or codes."
- Images go inline (cid) so Outlook shows them without "download pictures".
- New stage emails: **Matching label ready** (autorun finished: approve the research questions) replaces the old
  "Data set is ready" email; **Data set tagged** (tagging job finished: counts, review and approve).
- The Hunter-branded template is deleted.

## Accounts

InfoVision's Admins are Sweta Shah and Harish Thulasiram; the startup seed keeps only Khadar Syed as a Super Admin.

## Testing

Unit tests: outage classification, ordering and failover, waiting then resuming, give-up after the cap, state and
one-email-per-event, the layout (footer year, org panel, inline images). Live: Testing Org with VyceAI (in
maintenance) ahead of NVIDIA and Azure must fail over and email its admin; every email is sent to
khadar.syed@infovision.com through its real code path, in the lifecycle order above. No project is created.
