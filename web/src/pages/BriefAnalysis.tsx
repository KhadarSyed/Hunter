import { useEffect, useState } from "react";
import { DEMO_ANALYSIS_STEPS } from "../data/demo";
import { useProject } from "../lib/project-context";

type StepStatus = "completed" | "running" | "waiting";

function StepIcon({ status }: { status: StepStatus }) {
  if (status === "completed") {
    return (
      <div className="w-6 h-6 rounded-full bg-emerald-100 text-emerald-600 flex items-center justify-center shrink-0 animate-step-check">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
          <path d="M20 6L9 17l-5-5" />
        </svg>
      </div>
    );
  }
  if (status === "running") {
    return (
      <div className="w-6 h-6 rounded-full bg-blue-100 flex items-center justify-center shrink-0">
        <div className="w-2 h-2 rounded-full bg-blue-600 animate-pulse-dot" />
      </div>
    );
  }
  return (
    <div className="w-6 h-6 rounded-full bg-slate-100 border border-slate-200 shrink-0" />
  );
}

export function BriefAnalysis({ onNavigate }: { onNavigate: (page: string) => void }) {
  const { activeProject } = useProject();
  const [currentStep, setCurrentStep] = useState(0);
  const [complete, setComplete] = useState(false);

  useEffect(() => {
    if (currentStep < DEMO_ANALYSIS_STEPS.length) {
      const timer = setTimeout(() => setCurrentStep((c) => c + 1), 900);
      return () => clearTimeout(timer);
    } else {
      const timer = setTimeout(() => setComplete(true), 600);
      return () => clearTimeout(timer);
    }
  }, [currentStep]);

  const getStatus = (index: number): StepStatus => {
    if (index < currentStep) return "completed";
    if (index === currentStep && !complete) return "running";
    if (complete) return "completed";
    return "waiting";
  };

  return (
    <div className="p-8 max-w-2xl mx-auto space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Brief Analysis</h1>
          <p className="text-sm text-slate-500 mt-0.5">{activeProject?.name ?? "New Project"}</p>
        </div>
        {complete && (
          <button
            onClick={() => onNavigate("brief-scope-review")}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors shadow-sm animate-fade-in"
          >
            Review Results
          </button>
        )}
      </div>

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
          <span className="text-sm font-semibold text-slate-900">
            {complete ? "Analysis Complete" : "Analyzing Brief"}
          </span>
          {complete ? (
            <span className="text-xs font-medium text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-full">
              Complete
            </span>
          ) : (
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <div className="w-3 h-3 border-2 border-blue-200 border-t-blue-600 rounded-full animate-spin" />
              Processing
            </div>
          )}
        </div>

        <div className="p-6 space-y-1">
          {DEMO_ANALYSIS_STEPS.map((step, i) => {
            const status = getStatus(i);
            return (
              <div
                key={i}
                className={`flex items-center gap-3 py-3 px-3 rounded-lg transition-all ${
                  status === "running" ? "bg-blue-50/50" : ""
                } ${status === "waiting" ? "opacity-40" : ""}`}
              >
                <StepIcon status={status} />
                <span className={`text-sm ${
                  status === "completed" ? "text-slate-700" :
                  status === "running" ? "text-blue-700 font-medium" :
                  "text-slate-400"
                }`}>
                  {step.label}
                </span>
                {status === "completed" && (
                  <span className="text-xs text-slate-300 ml-auto">Done</span>
                )}
                {status === "running" && (
                  <span className="text-xs text-blue-500 ml-auto font-medium">Running</span>
                )}
                {status === "waiting" && (
                  <span className="text-xs text-slate-300 ml-auto">Waiting</span>
                )}
              </div>
            );
          })}
        </div>

        {complete && (
          <div className="px-6 py-4 bg-slate-50/50 border-t border-slate-100 animate-fade-in">
            <div className="grid grid-cols-4 gap-4 text-center">
              <div>
                <div className="text-lg font-semibold text-slate-900 tabular-nums">1</div>
                <div className="text-xs text-slate-400">Attempt</div>
              </div>
              <div>
                <div className="text-lg font-semibold text-emerald-600 tabular-nums">0</div>
                <div className="text-xs text-slate-400">Errors</div>
              </div>
              <div>
                <div className="text-lg font-semibold text-slate-900 tabular-nums">8</div>
                <div className="text-xs text-slate-400">Questions</div>
              </div>
              <div>
                <div className="text-lg font-semibold text-slate-900">High</div>
                <div className="text-xs text-slate-400">Confidence</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
