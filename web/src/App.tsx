import { useState, useEffect, useRef, useCallback, type ComponentType } from "react";
import { Sidebar } from "./components/Sidebar";
import { FloatingProgressPanel } from "./components/FloatingProgressPanel";
import { AuthProvider, useAuth } from "./context/auth-context";
import { DemoStateProvider, useDemoState } from "./context/demo-state";
import { ProjectProvider, useProject, type ProjectType } from "./context/project-context";
import { intelApi } from "./services/intel-api";
import { LoginPage } from "./pages/LoginPage";
import { ChangePasswordPage } from "./pages/ChangePasswordPage";
import { LandingPage } from "./pages/LandingPage";
import { Dashboard } from "./pages/Dashboard";
import { NewProject } from "./pages/NewProject";
import { ProjectsPage } from "./pages/ProjectsPage";
import { BriefAnalysis } from "./pages/BriefAnalysis";
import { BriefScopeReview } from "./pages/BriefScopeReview";
import { BackgroundResearch } from "./pages/BackgroundResearch";
import { SearchStrategy } from "./pages/SearchStrategy";
import { QueryEvaluation } from "./pages/QueryEvaluation";
import { DataSources } from "./pages/DataSources";
import { WorkflowOverview } from "./pages/WorkflowOverview";
import { ResearchPlan } from "./pages/ResearchPlan";
import { ResearchExecution } from "./pages/ResearchExecution";
import { EvidenceLibrary } from "./pages/EvidenceLibrary";
import { AnalysisPage } from "./pages/AnalysisPage";
import { InsightsPage } from "./pages/InsightsPage";
import { StorylinePage } from "./pages/StorylinePage";
import { SlideIntelligencePage } from "./pages/SlideIntelligencePage";
import { PresentationComposerPage } from "./pages/PresentationComposerPage";
import { PowerPointRendererPage } from "./pages/PowerPointRendererPage";
import { WordRendererPage } from "./pages/WordRendererPage";
import { PublishingGatewayPage } from "./pages/PublishingGatewayPage";
import { PipelineOrchestratorPage } from "./pages/PipelineOrchestratorPage";
import { DeliverablesPage } from "./pages/DeliverablesPage";
import { QCUpload } from "./pages/QCUpload";
import { QCFieldMapping } from "./pages/QCFieldMapping";
import { QCResults } from "./pages/QCResults";
import { QCExport } from "./pages/QCExport";

type PageProps = { onNavigate: (page: string) => void };

/** Single page registry: the key is the page id used by onNavigate(...) and the sidebar. */
const PAGES = {
  landing: LandingPage,
  dashboard: Dashboard,
  projects: ProjectsPage,
  "qc-projects": (p: PageProps) => <ProjectsPage {...p} projectType="monitoring_qc" />,
  "new-project": NewProject,
  "new-qc-project": (p: PageProps) => <NewProject {...p} projectType="monitoring_qc" />,
  "edit-project": (p: PageProps) => <NewProject {...p} mode="edit" />,
  "edit-qc-project": (p: PageProps) => <NewProject {...p} projectType="monitoring_qc" mode="edit" />,
  "brief-analysis": BriefAnalysis,
  "brief-scope-review": BriefScopeReview,
  "background-research": BackgroundResearch,
  "search-strategy": SearchStrategy,
  "query-evaluation": QueryEvaluation,
  "data-sources": DataSources,
  workflow: WorkflowOverview,
  "research-plan": ResearchPlan,
  "research-execution": ResearchExecution,
  "evidence-library": EvidenceLibrary,
  analysis: AnalysisPage,
  insights: InsightsPage,
  storyline: StorylinePage,
  "slide-intelligence": SlideIntelligencePage,
  "presentation-composer": PresentationComposerPage,
  "powerpoint-renderer": PowerPointRendererPage,
  "word-renderer": WordRendererPage,
  "publishing-gateway": PublishingGatewayPage,
  "pipeline-orchestrator": PipelineOrchestratorPage,
  deliverables: DeliverablesPage,
  "qc-upload": QCUpload,
  "qc-field-mapping": QCFieldMapping,
  "qc-results": QCResults,
  "qc-export": QCExport,
} satisfies Record<string, ComponentType<PageProps>>;

export type Page = keyof typeof PAGES;

const isPage = (p: string): p is Page => p in PAGES;

/** URL shape: `/{projectId}/{pageSlug}` once a project is active, else `/{pageSlug}` —
 * the page slug is the same id used internally (PAGES keys / onNavigate strings), so
 * there is exactly one name for each page, not a separate URL-vs-internal mapping. */
function parseUrl(pathname: string): { projectId: number | null; page: Page | null } {
  const segments = pathname.split("/").filter(Boolean).map(decodeURIComponent);
  if (segments.length === 0) return { projectId: null, page: null };
  const maybeId = Number(segments[0]);
  if (Number.isInteger(maybeId) && maybeId > 0) {
    const pageSeg = segments[1];
    return { projectId: maybeId, page: pageSeg && isPage(pageSeg) ? pageSeg : null };
  }
  return { projectId: null, page: isPage(segments[0]) ? segments[0] : null };
}

function buildUrl(projectId: number | null, page: Page): string {
  return projectId ? `/${projectId}/${page}` : `/${page}`;
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

  const hydrateProjectFromUrl = useCallback((projectId: number) => {
    if (projectId === activeProjectRef.current?.id) return;
    intelApi.getProject(projectId).then((p) => {
      setActiveProject({
        id: p.id, name: p.project_name,
        project_type: (p.project_type as ProjectType) || "research",
        brand: p.brand ?? null,
      });
    }).catch(() => { /* stale/invalid project id in the URL — keep whatever page was requested */ });
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
    if (!hydrated) return;
    const url = buildUrl(activeProject?.id ?? null, page);
    if (window.location.pathname !== url) window.history.replaceState(null, "", url);
  }, [page, activeProject?.id, hydrated]);

  const navigate = (p: string) => {
    if (!isPage(p)) { console.warn(`Unknown page "${p}"`); return; }
    setPageState(p);
    window.history.pushState(null, "", buildUrl(activeProject?.id ?? null, p));
  };

  const CurrentPage: ComponentType<PageProps> = PAGES[page];

  return (
    <>
      <div className="flex h-screen bg-white font-sans text-slate-900">
        {page !== "landing" && <Sidebar currentPage={page} onNavigate={navigate} />}
        <div className="flex-1 flex flex-col min-w-0">
          <main className="flex-1 overflow-auto bg-slate-50/50">
            <CurrentPage onNavigate={navigate} />
          </main>
        </div>
      </div>
      {/* Sibling to the page outlet above, not nested inside it — this is what
          lets it persist across `page` navigation while a stage keeps running
          in the background. */}
      <FloatingProgressPanel />
    </>
  );
}

function AuthGate() {
  const { user, loading } = useAuth();
  if (loading) return <div className="flex items-center justify-center min-h-screen text-slate-400">Loading…</div>;
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
