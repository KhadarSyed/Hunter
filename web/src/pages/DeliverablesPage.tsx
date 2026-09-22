import { useState, useEffect, useRef, useCallback } from "react";
import { intelApi } from "../lib/intel-api";
import { useActiveProjectId } from "../lib/project-context";

type Phase =
  | "idle"
  | "composing"
  | "rendering_pptx"
  | "rendering_word"
  | "validating"
  | "done"
  | "error";

interface StepDef {
  key: Phase;
  label: string;
}

const STEPS: StepDef[] = [
  { key: "composing", label: "Composing presentation" },
  { key: "rendering_pptx", label: "Rendering PowerPoint" },
  { key: "rendering_word", label: "Rendering Word document" },
  { key: "validating", label: "Running validation" },
];

const PURPOSE_COLORS: Record<string, string> = {
  cover: "bg-purple-100 text-purple-700",
  agenda: "bg-slate-100 text-slate-700",
  executive_summary: "bg-blue-100 text-blue-700",
  context: "bg-cyan-100 text-cyan-700",
  methodology: "bg-gray-100 text-gray-700",
  key_finding: "bg-emerald-100 text-emerald-700",
  trend: "bg-teal-100 text-teal-700",
  theme: "bg-indigo-100 text-indigo-700",
  competitive: "bg-orange-100 text-orange-700",
  audience: "bg-pink-100 text-pink-700",
  sentiment: "bg-rose-100 text-rose-700",
  timeline: "bg-sky-100 text-sky-700",
  opportunity: "bg-lime-100 text-lime-700",
  risk: "bg-red-100 text-red-700",
  recommendation: "bg-amber-100 text-amber-700",
  conclusion: "bg-violet-100 text-violet-700",
  appendix: "bg-stone-100 text-stone-700",
};

function stepIndex(phase: Phase): number {
  const idx = STEPS.findIndex((s) => s.key === phase);
  return idx === -1 ? STEPS.length : idx;
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function DeliverablesPage({ onNavigate }: { onNavigate: (page: string) => void }) {
  const projectId = useActiveProjectId() ?? 1;

  const [phase, setPhase] = useState<Phase>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const [prereqValid, setPrereqValid] = useState<boolean | null>(null);
  const [prereqBlockers, setPrereqBlockers] = useState<string[]>([]);

  const [presentationId, setPresentationId] = useState<number | null>(null);
  const [pptxUrl, setPptxUrl] = useState<string | null>(null);
  const [pptxError, setPptxError] = useState<string | null>(null);
  const [wordUrl, setWordUrl] = useState<string | null>(null);
  const [wordError, setWordError] = useState<string | null>(null);

  const [validationResult, setValidationResult] = useState<any>(null);
  const [readinessResult, setReadinessResult] = useState<any>(null);
  const [validationOpen, setValidationOpen] = useState(false);

  const [slides, setSlides] = useState<any[]>([]);
  const [overviewOpen, setOverviewOpen] = useState(false);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const abortRef = useRef(false);

  useEffect(() => {
    intelApi.composerValidatePrereqs(projectId).then((res: any) => {
      setPrereqValid(res.valid);
      setPrereqBlockers(res.blockers || []);
    }).catch(() => {
      setPrereqValid(false);
      setPrereqBlockers(["Could not verify prerequisites — check backend connection"]);
    });
  }, [projectId]);

  useEffect(() => {
    const running = phase !== "idle" && phase !== "done" && phase !== "error";
    if (running) {
      setElapsed(0);
      timerRef.current = setInterval(() => {
        setElapsed((prev) => prev + 1);
      }, 1000);
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [phase]);

  const pollStatus = useCallback(async (
    statusFn: (jobId: string) => Promise<any>,
    jobId: string
  ): Promise<string> => {
    for (;;) {
      if (abortRef.current) return "aborted";
      const res = await statusFn(jobId);
      const s = res.status || res.state || "";
      if (s === "completed" || s === "failed") return s;
      await sleep(3000);
    }
  }, []);

  const handleGenerate = useCallback(async () => {
    abortRef.current = false;
    setError(null);
    setPptxUrl(null);
    setPptxError(null);
    setWordUrl(null);
    setWordError(null);
    setValidationResult(null);
    setReadinessResult(null);
    setSlides([]);
    setPresentationId(null);

    try {
      setPhase("composing");
      await intelApi.composerGenerate(projectId);

      const list = await intelApi.composerList(projectId);
      if (!list || list.length === 0) {
        throw new Error("No presentation was created");
      }
      const presId = list[list.length - 1].id;
      setPresentationId(presId);

      if (abortRef.current) return;

      setPhase("rendering_pptx");
      try {
        const pptxJob = await intelApi.rendererRender(presId);
        const pptxJobId = pptxJob.job_id;
        const pptxStatus = await pollStatus(intelApi.rendererStatus, pptxJobId);
        if (pptxStatus === "completed") {
          const dl = intelApi.rendererDownloadUrl(pptxJobId);
          setPptxUrl(dl);
        } else {
          setPptxError("PowerPoint render failed");
        }
      } catch (e: any) {
        setPptxError(e.message || "PowerPoint render failed");
      }

      if (abortRef.current) return;

      setPhase("rendering_word");
      try {
        const wordJob = await intelApi.wordRender(presId);
        const wordJobId = wordJob.job_id;
        const wordStatus = await pollStatus(intelApi.wordRenderStatus, wordJobId);
        if (wordStatus === "completed") {
          const dl = intelApi.wordDownloadUrl(wordJobId);
          setWordUrl(dl);
        } else {
          setWordError("Word render failed");
        }
      } catch (e: any) {
        setWordError(e.message || "Word render failed");
      }

      if (abortRef.current) return;

      setPhase("validating");
      try {
        const [valRes, readRes] = await Promise.all([
          intelApi.pubValidate(projectId, presId).catch(() => null),
          intelApi.pubReadiness(projectId, presId).catch(() => null),
        ]);
        setValidationResult(valRes);
        setReadinessResult(readRes);
      } catch {
        // validation is non-critical
      }

      try {
        const slideData = await intelApi.composerSlides(presId);
        setSlides(Array.isArray(slideData) ? slideData : []);
      } catch {
        setSlides([]);
      }

      setPhase("done");
    } catch (e: any) {
      setError(e.message || "Pipeline failed");
      setPhase("error");
    }
  }, [projectId, pollStatus]);

  const handleRevalidate = async () => {
    if (!presentationId) return;
    try {
      const [valRes, readRes] = await Promise.all([
        intelApi.pubValidate(projectId, presentationId).catch(() => null),
        intelApi.pubReadiness(projectId, presentationId).catch(() => null),
      ]);
      setValidationResult(valRes);
      setReadinessResult(readRes);
    } catch {
      // non-critical
    }
  };

  const formatElapsed = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
  };

  const readinessScore = readinessResult?.readiness_score ?? null;

  const isRunning = phase !== "idle" && phase !== "done" && phase !== "error";

  if (prereqValid === false) {
    return (
      <div className="max-w-6xl mx-auto px-8 py-10">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-slate-900">Deliverables</h1>
          <p className="text-sm text-slate-500 mt-1">Generate and download your research deliverables</p>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-12 text-center">
          <svg className="w-12 h-12 mx-auto mb-4 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
          </svg>
          <h2 className="text-base font-semibold text-slate-700 mb-2">Prerequisites Not Met</h2>
          <p className="text-sm text-slate-500 mb-4">
            Complete the following before generating deliverables:
          </p>
          {prereqBlockers.length > 0 && (
            <ul className="text-sm text-red-600 list-disc list-inside mb-6 text-left max-w-md mx-auto">
              {prereqBlockers.map((b, i) => (
                <li key={i}>{b}</li>
              ))}
            </ul>
          )}
          <button
            onClick={() => onNavigate("analysis")}
            className="px-5 py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            Go to Analysis
          </button>
        </div>
        <div className="flex items-center pt-6">
          <button
            onClick={() => onNavigate("analysis")}
            className="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
          >
            Back to Analysis
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto px-8 py-10 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Deliverables</h1>
          <p className="text-sm text-slate-500 mt-1">Generate and download your research deliverables</p>
        </div>
        <button
          onClick={handleGenerate}
          disabled={isRunning}
          className="px-5 py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm disabled:opacity-50"
        >
          {isRunning ? "Generating..." : phase === "done" ? "Regenerate Deliverables" : "Generate Deliverables"}
        </button>
      </div>

      {error && (
        <div className="rounded-lg p-3 text-sm bg-red-50 text-red-700 border border-red-200">
          {error}
        </div>
      )}

      {isRunning && (
        <div className="bg-white rounded-xl border border-slate-200 p-6">
          <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest mb-4">Pipeline Progress</div>
          <div className="space-y-3">
            {STEPS.map((step, idx) => {
              const current = stepIndex(phase);
              const isCompleted = idx < current;
              const isActive = idx === current;
              const isPending = idx > current;
              return (
                <div key={step.key} className="flex items-center gap-3">
                  {isCompleted && (
                    <svg className="w-5 h-5 text-emerald-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                  )}
                  {isActive && (
                    <svg className="w-5 h-5 text-blue-600 shrink-0 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" className="opacity-25" />
                      <path fill="currentColor" className="opacity-75" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  )}
                  {isPending && (
                    <div className="w-5 h-5 rounded-full border-2 border-slate-200 shrink-0" />
                  )}
                  <span className={`text-sm ${
                    isCompleted ? "text-slate-400 line-through" :
                    isActive ? "text-blue-600 font-medium" :
                    "text-slate-400"
                  }`}>
                    {step.label}
                  </span>
                  {isActive && (
                    <span className="text-xs text-blue-400 ml-auto">in progress</span>
                  )}
                </div>
              );
            })}
          </div>
          <div className="mt-4 pt-3 border-t border-slate-100 text-xs text-slate-400 tabular-nums">
            Elapsed: {formatElapsed(elapsed)}
          </div>
        </div>
      )}

      {phase === "done" && (
        <>
          <div>
            <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest mb-3">Downloads</div>
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                <div className="flex items-start gap-3 mb-3">
                  <div className="w-10 h-10 rounded-lg bg-orange-100 flex items-center justify-center shrink-0">
                    <svg className="w-5 h-5 text-orange-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
                    </svg>
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="text-sm font-semibold text-slate-900">PowerPoint Presentation</h3>
                    {pptxUrl ? (
                      <span className="inline-block mt-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-100 text-emerald-700">Ready</span>
                    ) : (
                      <span className="inline-block mt-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-slate-100 text-slate-500">
                        {pptxError ? "Failed" : "Not generated"}
                      </span>
                    )}
                    {pptxError && (
                      <p className="text-xs text-red-500 mt-1">{pptxError}</p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {pptxUrl ? (
                    <a
                      href={pptxUrl}
                      download
                      className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                    >
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                      </svg>
                      Download .pptx
                    </a>
                  ) : (
                    <button disabled className="flex-1 px-4 py-2.5 text-sm font-medium bg-slate-100 text-slate-400 rounded-lg cursor-not-allowed">
                      Download .pptx
                    </button>
                  )}
                  <button
                    onClick={handleGenerate}
                    disabled={isRunning}
                    className="px-3 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors disabled:opacity-50"
                  >
                    Regenerate
                  </button>
                </div>
              </div>

              <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                <div className="flex items-start gap-3 mb-3">
                  <div className="w-10 h-10 rounded-lg bg-blue-100 flex items-center justify-center shrink-0">
                    <svg className="w-5 h-5 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                    </svg>
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="text-sm font-semibold text-slate-900">Intelligence Brief</h3>
                    {wordUrl ? (
                      <span className="inline-block mt-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-100 text-emerald-700">Ready</span>
                    ) : (
                      <span className="inline-block mt-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-slate-100 text-slate-500">
                        {wordError ? "Failed" : "Not generated"}
                      </span>
                    )}
                    {wordError && (
                      <p className="text-xs text-red-500 mt-1">{wordError}</p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {wordUrl ? (
                    <a
                      href={wordUrl}
                      download
                      className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                    >
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                      </svg>
                      Download .docx
                    </a>
                  ) : (
                    <button disabled className="flex-1 px-4 py-2.5 text-sm font-medium bg-slate-100 text-slate-400 rounded-lg cursor-not-allowed">
                      Download .docx
                    </button>
                  )}
                  <button
                    onClick={handleGenerate}
                    disabled={isRunning}
                    className="px-3 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors disabled:opacity-50"
                  >
                    Regenerate
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <button
              onClick={() => setValidationOpen(!validationOpen)}
              className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-slate-50 transition-colors"
            >
              <div className="flex items-center gap-3">
                <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest">Validation Summary</div>
                {readinessScore !== null && (
                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
                    readinessScore >= 0.8 ? "bg-emerald-100 text-emerald-700" :
                    readinessScore >= 0.5 ? "bg-amber-100 text-amber-700" :
                    "bg-red-100 text-red-700"
                  }`}>
                    {Math.round(readinessScore * 100)}% ready
                  </span>
                )}
              </div>
              <svg
                className={`w-4 h-4 text-slate-400 transition-transform ${validationOpen ? "rotate-180" : ""}`}
                fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
              </svg>
            </button>
            {validationOpen && (
              <div className="px-5 pb-5 space-y-4">
                {readinessScore !== null && (
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs text-slate-500">Readiness Score</span>
                      <span className="text-xs font-medium text-slate-700 tabular-nums">{Math.round(readinessScore * 100)}%</span>
                    </div>
                    <div className="w-full h-2.5 bg-slate-100 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${
                          readinessScore >= 0.8 ? "bg-emerald-500" :
                          readinessScore >= 0.5 ? "bg-amber-500" :
                          "bg-red-500"
                        }`}
                        style={{ width: `${Math.round(readinessScore * 100)}%` }}
                      />
                    </div>
                  </div>
                )}

                {validationResult?.issues && validationResult.issues.length > 0 && (
                  <div>
                    <div className="text-xs font-semibold text-slate-600 mb-2">Issues</div>
                    <div className="space-y-1.5">
                      {validationResult.issues.map((issue: any, i: number) => (
                        <div key={i} className="flex items-start gap-2 text-sm">
                          <span className={`shrink-0 mt-0.5 px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase ${
                            issue.severity === "critical" ? "bg-red-100 text-red-700" :
                            issue.severity === "major" ? "bg-orange-100 text-orange-700" :
                            issue.severity === "minor" ? "bg-yellow-100 text-yellow-600" :
                            "bg-blue-100 text-blue-600"
                          }`}>
                            {issue.severity || "info"}
                          </span>
                          <span className="text-slate-700">{issue.description || issue.message || String(issue)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {(!validationResult?.issues || validationResult.issues.length === 0) && readinessScore !== null && (
                  <p className="text-sm text-emerald-600 font-medium">No validation issues found</p>
                )}

                <button
                  onClick={handleRevalidate}
                  className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 transition-colors"
                >
                  Run Validation
                </button>
              </div>
            )}
          </div>

          {slides.length > 0 && (
            <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
              <button
                onClick={() => setOverviewOpen(!overviewOpen)}
                className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-slate-50 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest">Presentation Overview</div>
                  <span className="text-xs text-slate-400">{slides.length} slides</span>
                </div>
                <svg
                  className={`w-4 h-4 text-slate-400 transition-transform ${overviewOpen ? "rotate-180" : ""}`}
                  fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                </svg>
              </button>
              {overviewOpen && (
                <div className="px-5 pb-5">
                  <div className="divide-y divide-slate-50">
                    {slides.map((slide: any, idx: number) => (
                      <div key={slide.id || idx} className="flex items-center gap-3 py-2.5">
                        <span className="text-xs font-mono text-slate-400 w-6 text-right shrink-0">{idx + 1}</span>
                        <span className={`px-1.5 py-0.5 rounded text-[9px] font-semibold shrink-0 ${
                          PURPOSE_COLORS[slide.slide_purpose] || "bg-slate-100 text-slate-600"
                        }`}>
                          {(slide.slide_purpose || "content").replace(/_/g, " ").toUpperCase()}
                        </span>
                        <span className="text-sm text-slate-700 truncate flex-1">{slide.title}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {phase === "idle" && (
        <div className="bg-white rounded-xl border border-slate-200 p-12 text-center">
          <svg className="w-16 h-16 mx-auto mb-4 text-slate-200" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
          </svg>
          <h2 className="text-base font-semibold text-slate-700 mb-1">No deliverables generated yet</h2>
          <p className="text-sm text-slate-400">
            Click "Generate Deliverables" to compose the presentation, render PowerPoint and Word files, and run quality validation.
          </p>
        </div>
      )}

      <div className="flex items-center pt-6">
        <button
          onClick={() => onNavigate("analysis")}
          className="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
        >
          Back to Analysis
        </button>
      </div>
    </div>
  );
}
