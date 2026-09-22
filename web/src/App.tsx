import { useState, useEffect, useRef } from "react";
import { Sidebar } from "./components/Sidebar";
import { LandingPage } from "./pages/LandingPage";
import { Dashboard } from "./pages/Dashboard";
import { NewProject } from "./pages/NewProject";
import { BriefAnalysis } from "./pages/BriefAnalysis";
import { BriefScopeReview } from "./pages/BriefScopeReview";
import { BackgroundResearch } from "./pages/BackgroundResearch";
import { SearchStrategy } from "./pages/SearchStrategy";
import { DataSources } from "./pages/DataSources";
import { WorkflowOverview } from "./pages/WorkflowOverview";
import { ResearchExecution } from "./pages/ResearchExecution";
import { AnalysisPage } from "./pages/AnalysisPage";
import { DeliverablesPage } from "./pages/DeliverablesPage";
import { QCUpload } from "./pages/QCUpload";
import { QCFieldMapping } from "./pages/QCFieldMapping";
import { QCResults } from "./pages/QCResults";
import { QCExport } from "./pages/QCExport";
import { DemoStateProvider, useDemoState } from "./lib/demo-state";
import { ProjectProvider, useProject } from "./lib/project-context";

export type Page =
  | "landing"
  | "dashboard"
  | "new-project"
  | "new-qc-project"
  | "brief-analysis"
  | "brief-scope-review"
  | "background-research"
  | "search-strategy"
  | "data-sources"
  | "workflow"
  | "research-execution"
  | "analysis"
  | "deliverables"
  | "qc-upload"
  | "qc-field-mapping"
  | "qc-results"
  | "qc-export";

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

  const navigate = (p: string) => setPage(p as Page);

  return (
    <ProjectProvider>
      <DemoStateProvider>
        <ProjectDemoSync>
          <div className="flex h-screen bg-white font-sans text-slate-900">
            {page !== "landing" && <Sidebar currentPage={page} onNavigate={navigate} />}
            <div className="flex-1 flex flex-col min-w-0">
              <main className="flex-1 overflow-auto bg-slate-50/50">
                {page === "landing" && <LandingPage onNavigate={navigate} />}
                {page === "dashboard" && <Dashboard onNavigate={navigate} />}
                {page === "new-project" && <NewProject onNavigate={navigate} />}
                {page === "new-qc-project" && <NewProject onNavigate={navigate} projectType="monitoring_qc" />}
                {page === "brief-analysis" && <BriefAnalysis onNavigate={navigate} />}
                {page === "brief-scope-review" && <BriefScopeReview onNavigate={navigate} />}
                {page === "background-research" && <BackgroundResearch onNavigate={navigate} />}
                {page === "search-strategy" && <SearchStrategy onNavigate={navigate} />}
                {page === "data-sources" && <DataSources onNavigate={navigate} />}
                {page === "workflow" && <WorkflowOverview onNavigate={navigate} />}
                {page === "research-execution" && <ResearchExecution onNavigate={navigate} />}
                {page === "analysis" && <AnalysisPage onNavigate={navigate} />}
                {page === "deliverables" && <DeliverablesPage onNavigate={navigate} />}
                {page === "qc-upload" && <QCUpload onNavigate={navigate} />}
                {page === "qc-field-mapping" && <QCFieldMapping onNavigate={navigate} />}
                {page === "qc-results" && <QCResults onNavigate={navigate} />}
                {page === "qc-export" && <QCExport onNavigate={navigate} />}
              </main>
            </div>
          </div>
        </ProjectDemoSync>
      </DemoStateProvider>
    </ProjectProvider>
  );
}
