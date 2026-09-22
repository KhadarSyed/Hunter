import type { ProjectSummary } from "../data/demo";
import type { Page } from "../App";

const PAGE_LABELS: Partial<Record<Page, string>> = {
  dashboard: "Dashboard",
  "new-project": "New Project",
  "brief-analysis": "Brief Analysis",
  "brief-scope-review": "Brief & Scope",
  "background-research": "Background Research",
  "search-strategy": "Search Strategy",
  workflow: "Workflow",
  "research-execution": "Research Execution",
};

export function TopHeader({
  project,
  currentPage,
  mode,
  onModeChange,
}: {
  project: ProjectSummary;
  currentPage: Page;
  mode: string;
  onModeChange: (m: "guided" | "accelerated" | "automated") => void;
}) {
  const modes = ["guided", "accelerated", "automated"] as const;

  return (
    <header className="h-14 border-b border-slate-200 bg-white flex items-center px-6 gap-6 shrink-0">
      <div className="flex items-center gap-3 min-w-0">
        <h2 className="text-sm font-semibold text-slate-900 truncate">{project.name}</h2>
        <span className="text-xs font-medium text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full whitespace-nowrap">
          {project.stage}
        </span>
      </div>

      <div className="flex items-center gap-2 ml-auto shrink-0">
        <div className="flex items-center gap-1.5 mr-4">
          <div className="w-24 h-1.5 bg-slate-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-600 rounded-full transition-all duration-500"
              style={{ width: `${project.progress}%` }}
            />
          </div>
          <span className="text-xs font-medium text-slate-500 tabular-nums">{project.progress}%</span>
        </div>

        <div className="flex items-center bg-slate-100 rounded-lg p-0.5 text-xs">
          {modes.map((m) => (
            <button
              key={m}
              onClick={() => onModeChange(m)}
              className={`px-2.5 py-1 rounded-md capitalize transition-all ${
                mode === m
                  ? "bg-white text-slate-900 shadow-sm font-medium"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {m}
            </button>
          ))}
        </div>

        <button className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors relative">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
            <path d="M13.73 21a2 2 0 0 1-3.46 0" />
          </svg>
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-blue-600 rounded-full" />
        </button>

        <div className="w-8 h-8 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs font-semibold">
          SS
        </div>
      </div>
    </header>
  );
}
