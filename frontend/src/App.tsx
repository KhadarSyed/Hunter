import { useState, useEffect, useRef, useCallback, type ComponentType } from "react";
import { Sidebar } from "./components/Sidebar";
import { IconRailSidebar } from "./components/IconRailSidebar";
import { AuthProvider, useAuth } from "./context/auth-context";
import { DemoStateProvider, useDemoState } from "./context/demo-state";
import { ProjectProvider, useProject, type ProjectType } from "./context/project-context";
import { intelApi } from "./services/intel-api";
import { PAGE_STAGE, gateRedirect } from "./hooks/useStageGate";
import { LoginPage } from "./pages/LoginPage";
import { ChangePasswordPage } from "./pages/ChangePasswordPage";
import { ResetPasswordPage } from "./pages/ResetPasswordPage";
import { SettingsPage } from "./pages/SettingsPage";
import { LandingPage } from "./pages/LandingPage";
import { Dashboard } from "./pages/Dashboard";
import { NewProject } from "./pages/NewProject";
import { ProjectsPage } from "./pages/ProjectsPage";
import { BriefAnalysis } from "./pages/BriefAnalysis";
import { BriefScopeReview } from "./pages/BriefScopeReview";
import { BackgroundResearch } from "./pages/BackgroundResearch";
import { SearchStrategy } from "./pages/SearchStrategy";
import { QueryEvaluation } from "./pages/QueryEvaluation";
import { DataSet } from "./pages/DataSet";
import { MatchingLabel } from "./pages/MatchingLabel";
import { ResearchPlan } from "./pages/ResearchPlan";
import { DeliverablesPage } from "./pages/DeliverablesPage";
import { UsagePage } from "./pages/UsagePage";

type PageProps = { onNavigate: (page: string) => void };

/** Single page registry: the key is the page id used by onNavigate(...) and the sidebar. */
const PAGES = {
  landing: LandingPage,
  dashboard: Dashboard,
  projects: ProjectsPage,
  "new-project": NewProject,
  "edit-project": (p: PageProps) => <NewProject {...p} mode="edit" />,
  "brief-analysis": BriefAnalysis,
  "brief-scope-review": BriefScopeReview,
  "background-research": BackgroundResearch,
  "search-strategy": SearchStrategy,
  "query-evaluation": QueryEvaluation,
  "matching-label": MatchingLabel,
  "data-set": DataSet,
  "research-plan": ResearchPlan,
  deliverables: DeliverablesPage,
  settings: SettingsPage,
  usage: UsagePage,
} satisfies Record<string, ComponentType<PageProps>>;

export type Page = keyof typeof PAGES;

const isPage = (p: string): p is Page => p in PAGES;

/** Pages where no specific project is "open" yet — these get the minimal
 * icon-rail sidebar. Every other page is a pipeline stage inside an opened
 * project and keeps the full stage-by-stage Sidebar. */
const BROWSING_PAGES = new Set<Page>([
  "landing", "projects",
  "new-project", "edit-project",
  "settings", "usage",
]);

/** URL shape: `/{projectId}/{pageSlug}` once a project is active, else `/{pageSlug}` —
 * the page slug is the same id used internally (PAGES keys / onNavigate strings), so
 * there is exactly one name for each page, not a separate URL-vs-internal mapping. */
function parseUrl(pathname: string): { projectId: number | null; page: Page | null } {
  // "data-sources" is the old name of the Data set page; old links and emails still open it
  const segments = pathname.split("/").filter(Boolean).map(decodeURIComponent).map((s) => (s === "data-sources" ? "data-set" : s));
  if (segments.length === 0) return { projectId: null, page: null };
  const maybeId = Number(segments[0]);
  if (Number.isInteger(maybeId) && maybeId > 0) {
    const pageSeg = segments[1];
    return { projectId: maybeId, page: pageSeg && isPage(pageSeg) ? pageSeg : null };
  }
  return { projectId: null, page: isPage(segments[0]) ? segments[0] : null };
}

function buildUrl(projectId: number | null, page: Page): string {
  // Usage & cost is not inside a project: it has its own Project filter (?project=), so it never takes the prefix
  return projectId && page !== "usage" ? `/${projectId}/${page}` : `/${page}`;
}

/** Routing + demo-sync shell — rendered inside ProjectProvider/DemoStateProvider so it
 * can read/write the active project as the URL and in-app navigation change. */
function AppShell() {
  const { activeProject, setActiveProject, projectVersion } = useProject();
  const { resetDemoState } = useDemoState();
  const prevVersion = useRef(projectVersion);
  const activeProjectRef = useRef(activeProject);
  activeProjectRef.current = activeProject;

  useEffect(() => {
    if (projectVersion !== prevVersion.current) {
      prevVersion.current = projectVersion;
      resetDemoState();
    }
  }, [projectVersion, resetDemoState]);

  const [page, setPageState] = useState<Page>(() => parseUrl(window.location.pathname).page ?? "landing");
  const [hydrated, setHydrated] = useState(false);
  // The project named in the URL while it is being fetched: until it lands no page renders and the URL is not
  // rewritten, or the previously active project's data would show (and load) under the requested URL.
  const [openingProjectId, setOpeningProjectId] = useState<number | null>(null);
  const pushNext = useRef(false);

  const hydrateProjectFromUrl = useCallback((projectId: number) => {
    if (projectId === activeProjectRef.current?.id) return;
    setOpeningProjectId(projectId);
    intelApi.getProject(projectId).then((p) => {
      if (p.archived_at) {           // an archived project in an old URL or bookmark is not reopened
        window.history.replaceState(null, "", buildUrl(null, "projects"));
        setPageState("projects");
        return;
      }
      setActiveProject({
        id: p.id, name: p.project_name,
        project_type: (p.project_type as ProjectType) || "research",
        brand: p.brand ?? null,
      });
    }).catch(() => { /* stale/invalid project id in the URL — keep whatever page was requested */ })
      .finally(() => setOpeningProjectId((id) => (id === projectId ? null : id)));
  }, [setActiveProject]);

  // Hydrate once on mount: a deep-linked/refreshed URL wins over the persisted project.
  useEffect(() => {
    const parsed = parseUrl(window.location.pathname);
    if (parsed.page) setPageState(parsed.page);
    if (parsed.projectId) hydrateProjectFromUrl(parsed.projectId);
    setHydrated(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Browser back/forward.
  useEffect(() => {
    const onPopState = () => {
      const parsed = parseUrl(window.location.pathname);
      setPageState(parsed.page ?? "landing");
      if (parsed.projectId) hydrateProjectFromUrl(parsed.projectId);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [hydrateProjectFromUrl]);

  // Keep the URL in sync (replaceState — no new history entry) whenever the resolved
  // page/project drifts from it, e.g. once setActiveProject's async update lands after
  // an onNavigate() call that fired before it (see navigate() below).
  useEffect(() => {
    if (!hydrated || openingProjectId !== null) return;
    const url = buildUrl(activeProject?.id ?? null, page);
    if (window.location.pathname !== url) {
      // Usage & cost keeps its filters in the query (a project card puts ?project= there before navigating): the
      // query moves to the new entry and comes off the page being left. Every other page drops the query.
      const carried = page === "usage" ? window.location.search : "";
      if (carried) window.history.replaceState(window.history.state, "", window.location.pathname);
      if (pushNext.current) window.history.pushState(null, "", url + carried);
      else window.history.replaceState(null, "", url + carried);
    }
    pushNext.current = false;
  }, [page, activeProject?.id, hydrated, openingProjectId]);

  // Push only after the project switch that usually accompanies a navigation has landed, so the new URL carries
  // the new project (building it here would read the previous project from this render's closure).
  const navigate = (p: string) => {
    if (!isPage(p)) { console.warn(`Unknown page "${p}"`); return; }
    pushNext.current = true;
    setPageState(p);
  };

  // Stage gating: a later stage never opens (by link, sidebar or a typed URL) until the stage before it is done.
  // On a failed lookup the page renders as asked; the server still refuses to start a locked stage.
  const [gateNotice, setGateNotice] = useState<string | null>(null);
  const [gateChecked, setGateChecked] = useState<string | null>(null);
  const gateKey = `${activeProject?.id ?? ""}:${page}`;
  useEffect(() => {
    const pid = activeProject?.id;
    if (!hydrated || openingProjectId !== null || !pid || !PAGE_STAGE[page]) { setGateChecked(gateKey); return; }
    let live = true;
    intelApi.projectGates(pid).then((r) => {
      if (!live) return;
      const redirect = gateRedirect(r.gates, page);
      if (redirect && isPage(redirect.target)) {
        setGateNotice(redirect.message);
        setPageState(redirect.target);
      }
    }).catch(() => { /* render the page as asked */ })
      .finally(() => { if (live) setGateChecked(gateKey); });
    return () => { live = false; };
  }, [page, activeProject?.id, hydrated, openingProjectId, gateKey]);
  useEffect(() => {
    if (!gateNotice) return;
    const t = window.setTimeout(() => setGateNotice(null), 6000);
    return () => window.clearTimeout(t);
  }, [gateNotice]);
  const gatePending = Boolean(activeProject?.id && PAGE_STAGE[page] && gateChecked !== gateKey);

  const CurrentPage: ComponentType<PageProps> = PAGES[page];

  return (
    <>
      <div className="flex h-screen bg-white font-sans text-slate-900">
        {BROWSING_PAGES.has(page) ? (
          <IconRailSidebar currentPage={page} onNavigate={navigate} />
        ) : (
          <Sidebar currentPage={page} onNavigate={navigate} />
        )}
        <div className="flex-1 flex flex-col min-w-0">
          <main className="flex-1 overflow-auto bg-slate-50/50">
            {gateNotice && (
              <div role="status" className="sticky top-0 z-30 flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-5 py-2.5 text-sm text-amber-800">
                <svg className="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 018 0v4" />
                </svg>
                <span>{gateNotice}</span>
                <button onClick={() => setGateNotice(null)} className="ml-auto text-amber-600 hover:text-amber-800" aria-label="Dismiss">×</button>
              </div>
            )}
            {openingProjectId !== null || gatePending ? (
              <div role="status" className="flex h-full items-center justify-center gap-3 text-sm text-slate-500">
                <span className="h-5 w-5 animate-spin rounded-full border-2 border-slate-200 border-t-[#5B2C9D]" />
                Opening project...
              </div>
            ) : (
              <CurrentPage onNavigate={navigate} />
            )}
          </main>
        </div>
      </div>
    </>
  );
}

function AuthGate() {
  const { user, loading } = useAuth();
  if (window.location.pathname === "/reset-password") return <ResetPasswordPage />;   // the emailed link, signed in or out
  if (loading) return <div className="flex items-center justify-center min-h-screen text-slate-700">Loading…</div>;
  if (!user) return <LoginPage />;
  if (user.must_change_password) return <ChangePasswordPage />;
  return (
    <ProjectProvider>
      <DemoStateProvider>
        <AppShell />
      </DemoStateProvider>
    </ProjectProvider>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AuthGate />
    </AuthProvider>
  );
}
