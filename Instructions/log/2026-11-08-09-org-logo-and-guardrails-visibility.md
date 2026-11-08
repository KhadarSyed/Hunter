# 2026-11-08 #09 — InfoVision logo (tenant logo placement) + "I don't see the guardrails"

**Request:** Show the InfoVision logo (https://www.infovision.com/wp-content/uploads/2024/12/Logo-1.svg) somewhere per
industry standard. Also: "I don't see the guardrails — why?"

**Guardrails:** backend returns InfoVision's guardrail to Khadar (now InfoVision Admin). The tab is shown to
Admin/Analyser only; a page loaded while Khadar was still Super Admin keeps the old role until reload/sign-in again,
and production still has Khadar as Super Admin (no Guardrails tab there). Verified in a browser after sign-in:
Settings → Guardrails lists "Instructions/Guardrail Prompt".

**Logo (multi-tenant convention: vendor mark stays, the customer's logo marks the workspace):**
- Stored InfoVision's SVG as `organizations.logo_url` (org 5) as a data: URI (3.8 KB, checked: no script/handlers),
  so it works offline and is not hot-linked.
- `/api/auth/me` + login now return `org_logo_url` (`auth/router._to_response`, `LoginResponse`).
- `components/admin/adminUi.OrgLogo` variants: `square` (tables), `badge` (64 px nav rail), `wide` (profile card,
  dashboard header). Light, transparent logos get a dark chip; a logo with its own opaque background (corners
  filled — InfoVision's has a white rect) is shown as is. Decided on a canvas render, so default SVG colours count.
- Placed: `IconRailSidebar` under the AlphaMetricx mark (workspace badge, tooltip = org name), Settings profile
  card (wide), org dashboard / vendor drill-down header (wide), vendor org table (square).

Screens: `shots/infovision-org-dashboard.png`, `shots/infovision-settings-guardrails.png` (local).
