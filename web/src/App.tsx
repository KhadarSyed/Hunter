import { useState, useEffect, useRef, type ComponentType } from "react";
import { Sidebar } from "./components/Sidebar";
import { FloatingProgressPanel } from "./components/FloatingProgressPanel";
import { DemoStateProvider, useDemoState } from "./context/demo-state";
import { ProjectProvider, useProject } from "./context/project-context";
import { LandingPage } from "./pages/LandingPage";
import { Dashboard } from "./pages/Dashboard";
import { NewProject } from "./pages/NewProject";
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
  "new-project": NewProject,
  "new-qc-project": (p: PageProps) => <NewProject {...p} projectType="monitoring_qc" />,
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

function ProjectDemoSync({ children }: { children: React.ReactNode }) {
  const { projectVersion } = useProject();
  const { resetDemoState } = useDemoState();
  const prevVersion = useRef(projectVersion);

  useEffect(() => {
    if (projectVersion !== prevVersion.current) {
      prevVersion.current = projectVersion;
      resetDemoState();
    }
  }, [projectVersion, resetDemoState]);

  return <>{children}</>;
}

export default function App() {
  const [page, setPage] = useState<Page>("landing");

  const navigate = (p: string) => {
    if (isPage(p)) setPage(p);
    else console.warn(`Unknown page "${p}"`);
  };

  const CurrentPage: ComponentType<PageProps> = PAGES[page];

  return (
    <ProjectProvider>
      <DemoStateProvider>
        <ProjectDemoSync>
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
        </ProjectDemoSync>
      </DemoStateProvider>
    </ProjectProvider>
  );
}
