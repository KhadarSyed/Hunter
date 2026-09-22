import { DEMO_WORKFLOW_STAGES } from "../data/demo";
import { useProject } from "../lib/project-context";

function StageCard({ stage, index, onClick }: { stage: typeof DEMO_WORKFLOW_STAGES[0]; index: number; onClick?: () => void }) {
  const isCompleted = stage.status === "completed";
  const isPending = stage.status === "pending";

  return (
    <div
      className={`bg-white border rounded-xl p-5 shadow-sm transition-all cursor-pointer hover:shadow-md ${
        isCompleted ? "border-emerald-200" : "border-slate-200"
      }`}
      onClick={onClick}
    >
      <div className="flex items-center gap-3 mb-4">
        <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
          isCompleted
            ? "bg-emerald-100 text-emerald-600"
            : "bg-slate-100 text-slate-400"
        }`}>
          {isCompleted ? (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M20 6L9 17l-5-5" />
            </svg>
          ) : (
            index + 1
          )}
        </div>
        <div>
          <div className="text-sm font-semibold text-slate-900">{stage.label}</div>
          <div className={`text-xs font-medium ${isCompleted ? "text-emerald-600" : "text-slate-400"}`}>
            {stage.approval}
          </div>
        </div>
      </div>

      <div className="space-y-2.5 text-xs">
        <div className="flex justify-between">
          <span className="text-slate-400">Status</span>
          <span className={`font-medium ${isCompleted ? "text-emerald-600" : isPending ? "text-slate-400" : "text-blue-600"}`}>
            {isCompleted ? "Complete" : isPending ? "Pending" : "Running"}
          </span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-slate-400">Progress</span>
          <div className="flex items-center gap-2">
            <div className="w-16 h-1 bg-slate-100 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${isCompleted ? "bg-emerald-500" : "bg-blue-500"}`}
                style={{ width: `${stage.progress}%` }}
              />
            </div>
            <span className="font-medium text-slate-600 tabular-nums w-7 text-right">{stage.progress}%</span>
          </div>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-400">Owner</span>
          <span className="font-medium text-slate-600">{stage.owner}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-400">Inputs</span>
          <span className="font-medium text-slate-600 text-right max-w-[60%]">{stage.inputs}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-400">Outputs</span>
          <span className="font-medium text-slate-600 text-right max-w-[60%]">{stage.outputs}</span>
        </div>
      </div>
    </div>
  );
}

export function WorkflowOverview({ onNavigate }: { onNavigate: (page: string) => void }) {
  const { activeProject } = useProject();
  const handleClick = (stageId: string) => {
    if (stageId === "understanding") onNavigate("brief-analysis");
    if (stageId === "background") onNavigate("background-research");
    if (stageId === "search-strategy") onNavigate("search-strategy");
    if (stageId === "planning") onNavigate("research-execution");
  };

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-6 animate-fade-in">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Workflow</h1>
        <p className="text-sm text-slate-500 mt-0.5">{activeProject?.name ?? "Research Project"} — 10-stage pipeline</p>
      </div>

      <div className="flex items-center gap-0.5 py-4 overflow-x-auto">
        {DEMO_WORKFLOW_STAGES.map((stage, i) => (
          <div key={stage.id} className="flex items-center shrink-0">
            <div className={`flex items-center gap-1 px-2 py-1.5 rounded-lg text-[11px] font-semibold border ${
              stage.status === "completed"
                ? "text-emerald-700 bg-emerald-50 border-emerald-200"
                : "text-slate-400 bg-slate-50 border-slate-200"
            }`}>
              {stage.status === "completed" && (
                <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                  <path d="M20 6L9 17l-5-5" />
                </svg>
              )}
              {stage.label}
            </div>
            {i < DEMO_WORKFLOW_STAGES.length - 1 && (
              <svg className={`w-4 h-4 mx-0 ${stage.status === "completed" ? "text-emerald-300" : "text-slate-200"}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M9 18l6-6-6-6" />
              </svg>
            )}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-5 gap-3">
        {DEMO_WORKFLOW_STAGES.slice(0, 5).map((stage, i) => (
          <StageCard key={stage.id} stage={stage} index={i} onClick={() => handleClick(stage.id)} />
        ))}
      </div>
      <div className="grid grid-cols-5 gap-3">
        {DEMO_WORKFLOW_STAGES.slice(5).map((stage, i) => (
          <StageCard key={stage.id} stage={stage} index={i + 5} onClick={() => handleClick(stage.id)} />
        ))}
      </div>
    </div>
  );
}
