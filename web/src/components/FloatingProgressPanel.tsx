import { useCallback, useEffect, useRef, useState } from "react";
import { useAgentSocket } from "../hooks/useAgentSocket";
import type { WsMessage } from "../services/ws";

type StageStatus = "running" | "completed" | "failed" | "approved";

interface StageProgress {
  key: string;
  label: string;
  status: StageStatus;
  progressPct: number | null;
  message: string | null;
  updatedAt: number;
}

type StageMap = Record<string, StageProgress>;

interface Position {
  x: number;
  y: number;
}

// intelligence_api.py generates job_id as f"{stage}_{uuid.uuid4().hex[:N]}" at
// each of its `POST .../start` / `.../generate` / `.../upload` handlers
// (confirmed by reading every `job_id = f"..."` line in that file: research_,
// strategy_, eval_, plan_, exec_, exec_resume_, qc_run_). intel_job_update
// broadcasts never carry an explicit stage name, so the job_id prefix is the
// only reliable disambiguator. exec_resume_ must be checked before exec_.
const JOB_ID_STAGE_PREFIXES: { prefix: string; key: string; label: string }[] = [
  { prefix: "exec_resume_", key: "execution", label: "Research Execution" },
  { prefix: "research_", key: "research", label: "Background Research" },
  { prefix: "strategy_", key: "strategy", label: "Search Strategy" },
  { prefix: "eval_", key: "evaluation", label: "Sample Evaluation" },
  { prefix: "plan_", key: "plan", label: "Research Plan" },
  { prefix: "exec_", key: "execution", label: "Research Execution" },
  { prefix: "qc_run_", key: "qc", label: "QC Run" },
];

function stageFromJobId(jobId: string): { key: string; label: string } | null {
  const match = JOB_ID_STAGE_PREFIXES.find((entry) => jobId.startsWith(entry.prefix));
  return match ?? null;
}

// One-shot "*_approved" / final-approval events mark a terminal badge state
// (fired once on a user's Approve click), never a progress bar.
const APPROVAL_EVENT_STAGES: Record<string, { key: string; label: string }> = {
  intel_research_approved: { key: "research", label: "Background Research" },
  intel_brief_approved: { key: "brief", label: "Analyst Brief" },
  intel_strategy_approved: { key: "strategy", label: "Search Strategy" },
  intel_dataset_approved: { key: "dataset", label: "Data Sources" },
  intel_plan_approved: { key: "plan", label: "Research Plan" },
  intel_final_approval: { key: "final_approval", label: "Final Approval" },
};

function upsertStage(
  prev: StageMap,
  key: string,
  label: string,
  patch: Partial<Pick<StageProgress, "status" | "progressPct" | "message">>,
): StageMap {
  const existing = prev[key];
  return {
    ...prev,
    [key]: {
      key,
      label,
      status: existing?.status ?? "running",
      progressPct: existing?.progressPct ?? null,
      message: existing?.message ?? null,
      ...patch,
      updatedAt: Date.now(),
    },
  };
}

/**
 * Floating, draggable, minimize/maximize panel showing live progress for
 * whatever Intelligence Platform pipeline stage(s) are currently running.
 * Sourced purely from the shared WebSocket (via useAgentSocket) into local
 * state — single consumer, no Context/Redux needed (see restructure plan §4).
 */
export function FloatingProgressPanel() {
  const [stages, setStages] = useState<StageMap>({});
  const [isMinimized, setIsMinimized] = useState(true);
  const [position, setPosition] = useState<Position | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dragOffsetRef = useRef<{ offsetX: number; offsetY: number } | null>(null);

  const handleMessage = useCallback((msg: WsMessage) => {
    switch (msg.type) {
      case "intel_job_update": {
        const jobId = typeof msg.job_id === "string" ? msg.job_id : "";
        const stage = stageFromJobId(jobId);
        if (!stage) break;
        const status: StageStatus =
          msg.status === "completed" ? "completed" : msg.status === "failed" ? "failed" : "running";
        setStages((prev) =>
          upsertStage(prev, stage.key, stage.label, {
            status,
            progressPct: typeof msg.progress_pct === "number" ? msg.progress_pct : null,
            message:
              typeof msg.message === "string"
                ? msg.message
                : typeof msg.error === "string"
                  ? msg.error
                  : null,
          }),
        );
        break;
      }

      case "intel_execution_update": {
        const payload = (msg.payload ?? {}) as { total?: number; completed?: number; unit_id?: string };
        const pct =
          typeof payload.total === "number" && payload.total > 0 && typeof payload.completed === "number"
            ? Math.round((payload.completed / payload.total) * 100)
            : null;
        setStages((prev) =>
          upsertStage(prev, "execution", "Research Execution", {
            status: "running",
            progressPct: pct,
            message: typeof msg.event === "string" ? `${msg.event}: ${payload.unit_id ?? ""}`.trim() : null,
          }),
        );
        break;
      }

      case "intel_execution_complete": {
        setStages((prev) =>
          upsertStage(prev, "execution", "Research Execution", {
            status: "completed",
            progressPct: 100,
            message: "Execution complete",
          }),
        );
        break;
      }

      case "qc_progress": {
        setStages((prev) =>
          upsertStage(prev, "qc", "QC Run", {
            status: "running",
            progressPct: typeof msg.progress_pct === "number" ? msg.progress_pct : null,
            message: typeof msg.message === "string" ? msg.message : null,
          }),
        );
        break;
      }

      case "qc_complete": {
        setStages((prev) =>
          upsertStage(prev, "qc", "QC Run", { status: "completed", progressPct: 100, message: "QC run complete" }),
        );
        break;
      }

      case "qc_error": {
        setStages((prev) =>
          upsertStage(prev, "qc", "QC Run", {
            status: "failed",
            message: typeof msg.error === "string" ? msg.error : "QC run failed",
          }),
        );
        break;
      }

      // FUTURE (not yet broadcast by the backend as of this chunk — a parallel
      // task is adding it per the restructure plan §2/§5): the Pipeline
      // Orchestrator's full-mode run will emit {run_id, stage_id, status} once
      // its `_run_pipeline` background-thread fix lands. Wiring it in is a
      // one-line case, same shape as the cases above — no refactor needed:
      //
      // case "intel_pipeline_stage_update": {
      //   const status: StageStatus =
      //     msg.status === "completed" ? "completed" : msg.status === "failed" ? "failed" : "running";
      //   setStages((prev) =>
      //     upsertStage(prev, `pipeline:${msg.stage_id}`, `Pipeline — ${msg.stage_id}`, { status }),
      //   );
      //   break;
      // }

      default: {
        const approval = APPROVAL_EVENT_STAGES[msg.type];
        if (approval) {
          setStages((prev) => upsertStage(prev, approval.key, approval.label, { status: "approved" }));
        }
        break;
      }
    }
  }, []);

  useAgentSocket(handleMessage);

  // Drag: plain mousedown/mousemove/mouseup position tracking, cleaned up on
  // mouseup and on unmount. No drag library for one free-floating panel.
  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (!dragOffsetRef.current) return;
      setPosition({ x: e.clientX - dragOffsetRef.current.offsetX, y: e.clientY - dragOffsetRef.current.offsetY });
    };
    const handleMouseUp = () => {
      setIsDragging(false);
      dragOffsetRef.current = null;
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDragging]);

  const handleHeaderMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.parentElement?.getBoundingClientRect();
    dragOffsetRef.current = { offsetX: e.clientX - (rect?.left ?? 0), offsetY: e.clientY - (rect?.top ?? 0) };
    setIsDragging(true);
  };

  const stageList = Object.values(stages).sort((a, b) => b.updatedAt - a.updatedAt);
  const runningCount = stageList.filter((s) => s.status === "running").length;

  // Nothing has broadcast anything yet — stages with no broadcasts today
  // (Evidence Library, Insights, Storyline, Composer, Renderers, Publishing
  // Gateway, Slide Intelligence) correctly show nothing live. Don't fabricate.
  if (stageList.length === 0) return null;

  if (isMinimized) {
    return (
      <button
        type="button"
        onClick={() => setIsMinimized(false)}
        className="fixed bottom-4 right-4 z-[100] flex items-center gap-2 rounded-full bg-violet px-4 py-2.5 text-white shadow-lg shadow-violet/30 transition-opacity hover:opacity-90"
      >
        <span className={`h-2 w-2 rounded-full bg-white ${runningCount > 0 ? "animate-pulse-dot" : ""}`} />
        <span className="text-xs font-medium">
          {runningCount > 0 ? `${runningCount} running` : "Pipeline activity"}
        </span>
      </button>
    );
  }

  const panelStyle: React.CSSProperties = position
    ? { left: position.x, top: position.y }
    : { bottom: "1rem", right: "1rem" };

  return (
    <div className="fixed z-[100] w-96 rounded-xl border border-slate-200 bg-white shadow-2xl" style={panelStyle}>
      <div
        onMouseDown={handleHeaderMouseDown}
        className="flex cursor-move items-center justify-between rounded-t-xl bg-violet px-4 py-2.5 text-white"
      >
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full bg-white ${runningCount > 0 ? "animate-pulse-dot" : ""}`} />
          <span className="text-xs font-semibold">Pipeline Progress</span>
        </div>
        <button
          type="button"
          onClick={() => setIsMinimized(true)}
          className="rounded p-1 text-white/80 transition-colors hover:bg-white/10 hover:text-white"
          aria-label="Minimize"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
            <path d="M5 12h14" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      <div className="max-h-96 overflow-y-auto p-3">
        {stageList.map((stage) => (
          <StageRow key={stage.key} stage={stage} />
        ))}
      </div>
    </div>
  );
}

function StageRow({ stage }: { stage: StageProgress }) {
  const pct = stage.progressPct ?? (stage.status === "completed" || stage.status === "approved" ? 100 : 0);
  return (
    <div className="mb-2 rounded-lg border border-slate-100 bg-slate-50/60 p-2.5 last:mb-0">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-slate-700">{stage.label}</span>
        <StatusBadge status={stage.status} />
      </div>
      {stage.message && <div className="mb-1.5 truncate text-[11px] text-slate-500">{stage.message}</div>}
      {stage.status === "running" && (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
          <div className="h-full rounded-full bg-violet transition-all duration-300" style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: StageStatus }) {
  if (status === "approved") {
    return (
      <span className="rounded-full bg-qc-teal/10 px-2 py-0.5 text-[10px] font-medium text-qc-teal">Approved</span>
    );
  }
  if (status === "completed") {
    return (
      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-600">Done</span>
    );
  }
  if (status === "failed") {
    return <span className="rounded-full bg-red-50 px-2 py-0.5 text-[10px] font-medium text-red-600">Failed</span>;
  }
  return <span className="rounded-full bg-violet/10 px-2 py-0.5 text-[10px] font-medium text-violet">Running</span>;
}
