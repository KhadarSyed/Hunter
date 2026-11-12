/** URL <-> page mapping, kept free of React so it can be unit-tested (routing.test.ts). App.tsx owns the history
 * plumbing; PAGES there must have exactly these ids (enforced by `satisfies Record<Page, ...>`). */

export const PAGE_IDS = [
  "landing", "dashboard", "projects", "new-project", "edit-project", "brief-analysis", "brief-scope-review",
  "background-research", "search-strategy", "query-evaluation", "matching-label", "data-set", "research-plan",
  "deliverables", "settings", "usage", "admin", "org-dashboard",
] as const;

export type Page = (typeof PAGE_IDS)[number];

const PAGE_SET: ReadonlySet<string> = new Set(PAGE_IDS);

export const isPage = (p: string): p is Page => PAGE_SET.has(p);

/** Each role's home: a Super Admin lands on the platform dashboard, an Org Admin on the org dashboard. */
export function homeFor(role: string | undefined): Page {
  return role === "super_admin" ? "admin" : role === "admin" ? "org-dashboard" : "landing";
}

/** URL shape: `/{projectId}/{pageSlug}` once a project is active, else `/{pageSlug}` — the page slug is the same id
 * used internally (PAGES keys / onNavigate strings), so each page has exactly one name. */
export function parseUrl(pathname: string): { projectId: number | null; page: Page | null } {
  // "data-sources" is the old name of the Data set page; old links and emails still open it
  const segments = pathname.split("/").filter(Boolean).map(decodeURIComponent)
    .map((s) => (s === "data-sources" ? "data-set" : s));
  if (segments.length === 0) return { projectId: null, page: null };
  const maybeId = Number(segments[0]);
  if (Number.isInteger(maybeId) && maybeId > 0) {
    const pageSeg = segments[1];
    return { projectId: maybeId, page: pageSeg && isPage(pageSeg) ? pageSeg : null };
  }
  return { projectId: null, page: isPage(segments[0]) ? segments[0] : null };
}

export function buildUrl(projectId: number | null, page: Page): string {
  // Usage & cost is not inside a project: it has its own Project filter (?project=), so it never takes the prefix
  return projectId && page !== "usage" ? `/${projectId}/${page}` : `/${page}`;
}
