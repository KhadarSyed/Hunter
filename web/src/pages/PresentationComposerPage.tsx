import { useState, useEffect, useCallback, useRef } from "react";
import { intelApi } from "../lib/intel-api";
import type { PCPresentation, PCSlide, PCPresentationDetail, PCPresentationSummary, PCValidation } from "../data/contracts";
import { useActiveProjectId } from "../lib/project-context";

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

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-slate-100 text-slate-600",
  needs_review: "bg-amber-100 text-amber-700",
  approved: "bg-emerald-100 text-emerald-700",
  rejected: "bg-red-100 text-red-700",
};

function ConfidenceBar({ value, size = "sm" }: { value: number; size?: "sm" | "lg" }) {
  const pct = Math.round(value * 100);
  const color = pct >= 70 ? "bg-emerald-500" : pct >= 40 ? "bg-amber-500" : "bg-red-500";
  const h = size === "lg" ? "h-2.5" : "h-1.5";
  return (
    <div className="flex items-center gap-2">
      <div className={`flex-1 ${h} bg-slate-100 rounded-full overflow-hidden`}>
        <div className={`${h} ${color} rounded-full transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-500 w-8 text-right">{pct}%</span>
    </div>
  );
}

export function PresentationComposerPage({ onNavigate }: { onNavigate: (p: string) => void }) {
  const PROJECT_ID = useActiveProjectId() ?? 1;
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<PCPresentationSummary | null>(null);
  const [detail, setDetail] = useState<PCPresentationDetail | null>(null);
  const [selectedSlide, setSelectedSlide] = useState<PCSlide | null>(null);
  const [validation, setValidation] = useState<PCValidation | null>(null);
  const [editingTitle, setEditingTitle] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editingNarrative, setEditingNarrative] = useState(false);
  const [editNarrative, setEditNarrative] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [genStep, setGenStep] = useState("");
  const timerRef = useRef<ReturnType<typeof setInterval>>();

  useEffect(() => {
    if (generating) {
      setElapsed(0);
      setGenStep("Validating prerequisites...");
      const steps = [
        { t: 3, msg: "Auto-approving storyline..." },
        { t: 6, msg: "Building slide structure..." },
        { t: 12, msg: "Generating key messages (LLM)..." },
        { t: 20, msg: "Generating speaker notes (LLM)..." },
        { t: 35, msg: "Building content blocks..." },
        { t: 50, msg: "Computing confidence scores..." },
        { t: 65, msg: "Generating recommendations (LLM)..." },
        { t: 80, msg: "Finalizing presentation..." },
      ];
      timerRef.current = setInterval(() => {
        setElapsed((prev) => {
          const next = prev + 1;
          const step = [...steps].reverse().find((s) => next >= s.t);
          if (step) setGenStep(step.msg);
          return next;
        });
      }, 1000);
      return () => clearInterval(timerRef.current);
    } else {
      clearInterval(timerRef.current);
    }
  }, [generating]);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      const s = await intelApi.composerSummary(PROJECT_ID);
      setSummary(s);
      if (s.latest_presentation_id) {
        const d = await intelApi.composerDetail(s.latest_presentation_id);
        setDetail(d);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const handleGenerate = async () => {
    try {
      setGenerating(true);
      setError(null);
      const result = await intelApi.composerGenerate(PROJECT_ID);
      const d = await intelApi.composerDetail(result.presentation_id);
      setDetail(d);
      const s = await intelApi.composerSummary(PROJECT_ID);
      setSummary(s);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setGenerating(false);
    }
  };

  const handleApproveSlide = async (slideId: number) => {
    await intelApi.composerReviewSlide(slideId, "approved");
    if (detail) {
      const d = await intelApi.composerDetail(detail.presentation.id);
      setDetail(d);
      const s = d.slides.find((sl) => sl.id === slideId);
      if (s) setSelectedSlide(s);
    }
  };

  const handleRejectSlide = async (slideId: number) => {
    await intelApi.composerReviewSlide(slideId, "rejected");
    if (detail) {
      const d = await intelApi.composerDetail(detail.presentation.id);
      setDetail(d);
      const s = d.slides.find((sl) => sl.id === slideId);
      if (s) setSelectedSlide(s);
    }
  };

  const handleLockSlide = async (slideId: number) => {
    const slide = detail?.slides.find((s) => s.id === slideId);
    if (!slide) return;
    if (slide.is_locked) {
      await intelApi.composerUnlockSlide(slideId);
    } else {
      await intelApi.composerLockSlide(slideId);
    }
    if (detail) {
      const d = await intelApi.composerDetail(detail.presentation.id);
      setDetail(d);
      const s = d.slides.find((sl) => sl.id === slideId);
      if (s) setSelectedSlide(s);
    }
  };

  const handleSaveTitle = async () => {
    if (!selectedSlide) return;
    await intelApi.composerUpdateSlide(selectedSlide.id, { title: editTitle });
    setEditingTitle(false);
    if (detail) {
      const d = await intelApi.composerDetail(detail.presentation.id);
      setDetail(d);
      const s = d.slides.find((sl) => sl.id === selectedSlide.id);
      if (s) setSelectedSlide(s);
    }
  };

  const handleSaveNarrative = async () => {
    if (!selectedSlide) return;
    await intelApi.composerUpdateSlide(selectedSlide.id, { narrative: editNarrative });
    setEditingNarrative(false);
    if (detail) {
      const d = await intelApi.composerDetail(detail.presentation.id);
      setDetail(d);
      const s = d.slides.find((sl) => sl.id === selectedSlide.id);
      if (s) setSelectedSlide(s);
    }
  };

  const handleSelectLayout = async (slideId: number, layout: string) => {
    await intelApi.composerSelectLayout(slideId, layout, "Manually selected alternative");
    if (detail) {
      const d = await intelApi.composerDetail(detail.presentation.id);
      setDetail(d);
      const s = d.slides.find((sl) => sl.id === slideId);
      if (s) setSelectedSlide(s);
    }
  };

  const handleSelectVisual = async (slideId: number, visual: string) => {
    await intelApi.composerSelectVisual(slideId, visual);
    if (detail) {
      const d = await intelApi.composerDetail(detail.presentation.id);
      setDetail(d);
      const s = d.slides.find((sl) => sl.id === slideId);
      if (s) setSelectedSlide(s);
    }
  };

  const handleApprovePresentation = async () => {
    if (!detail) return;
    await intelApi.composerApprove(detail.presentation.id);
    const d = await intelApi.composerDetail(detail.presentation.id);
    setDetail(d);
    const s = await intelApi.composerSummary(PROJECT_ID);
    setSummary(s);
  };

  const handleRejectPresentation = async () => {
    if (!detail) return;
    await intelApi.composerReject(detail.presentation.id);
    const d = await intelApi.composerDetail(detail.presentation.id);
    setDetail(d);
    const s = await intelApi.composerSummary(PROJECT_ID);
    setSummary(s);
  };

  const handleValidate = async () => {
    if (!detail) return;
    const v = await intelApi.composerValidate(detail.presentation.id);
    setValidation(v);
  };

  if (loading) {
    return (
      <div className="p-8">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-slate-200 rounded w-64" />
          <div className="h-4 bg-slate-100 rounded w-96" />
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-slate-900">Presentation Composer</h1>
            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-600 text-white tracking-wider">
              STAGE 10
            </span>
          </div>
          <p className="text-sm text-slate-500 mt-1">
            Compose the presentation model — slide structure, layout, visuals, and evidence mapping
          </p>
        </div>
        <div className="flex items-center gap-2">
          {detail && (
            <>
              <button
                onClick={handleValidate}
                className="px-3 py-1.5 text-sm rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50"
              >
                Validate
              </button>
              {detail.presentation.status !== "approved" && (
                <>
                  <button
                    onClick={handleRejectPresentation}
                    className="px-3 py-1.5 text-sm rounded-lg border border-red-200 text-red-600 hover:bg-red-50"
                  >
                    Reject
                  </button>
                  <button
                    onClick={handleApprovePresentation}
                    className="px-3 py-1.5 text-sm rounded-lg bg-emerald-600 text-white hover:bg-emerald-700"
                  >
                    Approve Presentation
                  </button>
                </>
              )}
            </>
          )}
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="px-4 py-1.5 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {generating ? "Generating..." : detail ? "Regenerate" : "Generate Presentation"}
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-red-50 text-red-700 text-sm">{error}</div>
      )}

      {validation && (
        <div className={`p-4 rounded-xl border ${validation.valid ? "border-emerald-200 bg-emerald-50" : "border-red-200 bg-red-50"}`}>
          <div className="flex items-center gap-2 mb-2">
            <span className={`text-sm font-semibold ${validation.valid ? "text-emerald-700" : "text-red-700"}`}>
              {validation.valid ? "Validation Passed" : "Validation Failed"}
            </span>
          </div>
          {validation.issues && validation.issues.length > 0 && (
            <ul className="text-sm text-red-600 list-disc list-inside">
              {validation.issues.map((i, idx) => <li key={idx}>{i}</li>)}
            </ul>
          )}
          {validation.warnings && validation.warnings.length > 0 && (
            <ul className="text-sm text-amber-600 list-disc list-inside mt-1">
              {validation.warnings.map((w, idx) => <li key={idx}>{w}</li>)}
            </ul>
          )}
        </div>
      )}

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-5 gap-4">
          {[
            { label: "Presentations", value: summary.presentation_count },
            { label: "Status", value: summary.latest_status || "—" },
            { label: "Total Slides", value: summary.total_slides },
            { label: "Duration", value: `${summary.total_duration_minutes} min` },
            { label: "Approved", value: summary.slide_statuses?.approved || 0 },
          ].map((card) => (
            <div key={card.label} className="bg-white rounded-xl border border-slate-200 p-4">
              <div className="text-xs text-slate-400 font-medium uppercase tracking-wide">{card.label}</div>
              <div className="text-2xl font-bold text-slate-900 mt-1">{card.value}</div>
            </div>
          ))}
        </div>
      )}

      {generating && (
        <div className="bg-white rounded-xl border border-slate-200 p-12">
          <div className="max-w-md mx-auto text-center">
            <div className="w-16 h-16 mx-auto mb-5 relative">
              <svg className="animate-spin w-16 h-16" viewBox="0 0 64 64" fill="none">
                <circle cx="32" cy="32" r="28" stroke="#e2e8f0" strokeWidth="4" />
                <path d="M32 4a28 28 0 0 1 28 28" stroke="#3b82f6" strokeWidth="4" strokeLinecap="round" />
              </svg>
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="text-sm font-bold text-blue-600 tabular-nums">{elapsed}s</span>
              </div>
            </div>
            <h3 className="text-sm font-semibold text-slate-800 mb-2">Composing Presentation</h3>
            <p className="text-[13px] text-blue-600 font-medium mb-4">{genStep}</p>
            <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-1000 ease-out"
                style={{ width: `${Math.min(95, elapsed * 1.1)}%` }}
              />
            </div>
            <p className="text-[11px] text-slate-400 mt-3">
              LLM is generating key messages, speaker notes, and recommendations. This typically takes 30-90 seconds.
            </p>
          </div>
        </div>
      )}

      {!detail && !generating && (
        <div className="bg-white rounded-xl border border-slate-200 p-12 text-center">
          <div className="text-slate-400 text-sm">
            No presentation generated yet. Click "Generate Presentation" to compose slides from the approved storyline.
          </div>
        </div>
      )}

      {detail && (
        <div className="flex gap-6">
          {/* Slide List */}
          <div className="w-80 shrink-0 space-y-2">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-slate-700">Presentation Outline</h2>
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${STATUS_COLORS[detail.presentation.status] || STATUS_COLORS.draft}`}>
                {detail.presentation.status.toUpperCase()}
              </span>
            </div>
            {detail.slides.map((slide) => (
              <button
                key={slide.id}
                onClick={() => setSelectedSlide(slide)}
                className={`w-full text-left p-3 rounded-xl border transition-all ${
                  selectedSlide?.id === slide.id
                    ? "border-blue-300 bg-blue-50 shadow-sm"
                    : "border-slate-200 bg-white hover:border-slate-300"
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[10px] font-bold text-slate-400 w-5">{slide.slide_number}</span>
                  <span className={`px-1.5 py-0.5 rounded text-[9px] font-semibold ${PURPOSE_COLORS[slide.slide_purpose] || "bg-slate-100 text-slate-600"}`}>
                    {slide.slide_purpose.replace(/_/g, " ").toUpperCase()}
                  </span>
                  {slide.is_locked ? (
                    <span className="text-[9px] text-slate-400 ml-auto">Locked</span>
                  ) : null}
                  <span className={`ml-auto px-1.5 py-0.5 rounded text-[8px] font-semibold ${STATUS_COLORS[slide.status] || STATUS_COLORS.draft}`}>
                    {slide.status}
                  </span>
                </div>
                <div className="text-xs font-medium text-slate-800 truncate pl-5">{slide.title}</div>
                <div className="pl-5 mt-1">
                  <ConfidenceBar value={slide.overall_confidence} />
                </div>
              </button>
            ))}

            {/* Flow Analysis */}
            {detail.flow_analysis && (
              <div className="mt-4 p-3 rounded-xl border border-slate-200 bg-white">
                <div className="text-xs font-semibold text-slate-600 mb-2">Presentation Flow</div>
                <div className="flex flex-wrap gap-1">
                  {["opening", "context", "problem", "supporting_evidence", "insights", "business_impact", "recommendations", "conclusion"].map((stage) => (
                    <span
                      key={stage}
                      className={`px-1.5 py-0.5 rounded text-[9px] font-medium ${
                        detail.flow_analysis.stages_present.includes(stage)
                          ? "bg-emerald-100 text-emerald-700"
                          : "bg-red-50 text-red-400"
                      }`}
                    >
                      {stage.replace(/_/g, " ")}
                    </span>
                  ))}
                </div>
                <div className="text-[10px] text-slate-400 mt-2">
                  {detail.flow_analysis.flow_complete
                    ? "All flow stages covered"
                    : `Missing: ${detail.flow_analysis.stages_missing.join(", ")}`}
                </div>
              </div>
            )}

            <div className="mt-3 p-3 rounded-xl border border-slate-200 bg-white">
              <div className="text-xs font-semibold text-slate-600">Duration</div>
              <div className="text-lg font-bold text-slate-900">
                {detail.total_duration_minutes} min
              </div>
            </div>
          </div>

          {/* Slide Detail */}
          <div className="flex-1 min-w-0">
            {!selectedSlide ? (
              <div className="bg-white rounded-xl border border-slate-200 p-12 text-center text-slate-400 text-sm">
                Select a slide from the outline to view details
              </div>
            ) : (
              <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
                {/* Slide Header */}
                <div className="p-5 border-b border-slate-100">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold text-slate-400">Slide {selectedSlide.slide_number}</span>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${PURPOSE_COLORS[selectedSlide.slide_purpose] || "bg-slate-100 text-slate-600"}`}>
                        {selectedSlide.slide_purpose.replace(/_/g, " ").toUpperCase()}
                      </span>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${STATUS_COLORS[selectedSlide.status]}`}>
                        {selectedSlide.status}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => handleLockSlide(selectedSlide.id)}
                        className={`px-2 py-1 text-xs rounded border ${selectedSlide.is_locked ? "border-amber-300 bg-amber-50 text-amber-700" : "border-slate-200 text-slate-500 hover:bg-slate-50"}`}
                      >
                        {selectedSlide.is_locked ? "Unlock" : "Lock"}
                      </button>
                      <button
                        onClick={() => handleRejectSlide(selectedSlide.id)}
                        className="px-2 py-1 text-xs rounded border border-red-200 text-red-600 hover:bg-red-50"
                      >
                        Reject
                      </button>
                      <button
                        onClick={() => handleApproveSlide(selectedSlide.id)}
                        className="px-2 py-1 text-xs rounded bg-emerald-600 text-white hover:bg-emerald-700"
                      >
                        Approve
                      </button>
                    </div>
                  </div>

                  {/* Title */}
                  {editingTitle ? (
                    <div className="flex items-center gap-2">
                      <input
                        className="flex-1 text-lg font-bold text-slate-900 border border-blue-300 rounded-lg px-2 py-1"
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                      />
                      <button onClick={handleSaveTitle} className="px-2 py-1 text-xs rounded bg-blue-600 text-white">Save</button>
                      <button onClick={() => setEditingTitle(false)} className="px-2 py-1 text-xs rounded border text-slate-500">Cancel</button>
                    </div>
                  ) : (
                    <h2
                      className="text-lg font-bold text-slate-900 cursor-pointer hover:text-blue-600"
                      onClick={() => { setEditTitle(selectedSlide.title); setEditingTitle(true); }}
                    >
                      {selectedSlide.title}
                    </h2>
                  )}
                  {selectedSlide.subtitle && (
                    <p className="text-sm text-slate-500 mt-0.5">{selectedSlide.subtitle}</p>
                  )}
                </div>

                {/* Slide Body */}
                <div className="p-5 space-y-5">
                  {/* Key Message */}
                  {selectedSlide.key_message && (
                    <div className="p-3 rounded-lg bg-blue-50 border border-blue-100">
                      <div className="text-[10px] font-semibold text-blue-600 uppercase tracking-wide mb-1">Key Message</div>
                      <div className="text-sm text-blue-900">{selectedSlide.key_message}</div>
                    </div>
                  )}

                  {/* Narrative */}
                  <div>
                    <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Narrative</div>
                    {editingNarrative ? (
                      <div className="space-y-2">
                        <textarea
                          className="w-full text-sm text-slate-700 border border-blue-300 rounded-lg p-2 min-h-[80px]"
                          value={editNarrative}
                          onChange={(e) => setEditNarrative(e.target.value)}
                        />
                        <div className="flex gap-2">
                          <button onClick={handleSaveNarrative} className="px-2 py-1 text-xs rounded bg-blue-600 text-white">Save</button>
                          <button onClick={() => setEditingNarrative(false)} className="px-2 py-1 text-xs rounded border text-slate-500">Cancel</button>
                        </div>
                      </div>
                    ) : (
                      <p
                        className="text-sm text-slate-700 leading-relaxed cursor-pointer hover:bg-slate-50 rounded p-1 -m-1"
                        onClick={() => { setEditNarrative(selectedSlide.narrative || ""); setEditingNarrative(true); }}
                      >
                        {selectedSlide.narrative || <span className="text-slate-400 italic">No narrative — click to add</span>}
                      </p>
                    )}
                  </div>

                  {/* Business Objective */}
                  {selectedSlide.business_objective && (
                    <div>
                      <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Business Objective</div>
                      <p className="text-sm text-slate-600">{selectedSlide.business_objective}</p>
                    </div>
                  )}

                  {/* Layout & Visual Recommendations */}
                  <div className="grid grid-cols-2 gap-4">
                    <div className="p-3 rounded-lg border border-slate-200">
                      <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Layout</div>
                      <div className="text-sm font-medium text-slate-800">
                        {(selectedSlide.layout_recommendation || "—").replace(/_/g, " ")}
                      </div>
                      {selectedSlide.layout_rationale && (
                        <p className="text-xs text-slate-500 mt-1">{selectedSlide.layout_rationale}</p>
                      )}
                      {(selectedSlide.alt_layout_1 || selectedSlide.alt_layout_2) && (
                        <div className="mt-2 space-y-1">
                          <div className="text-[9px] text-slate-400 uppercase font-semibold">Alternatives</div>
                          {selectedSlide.alt_layout_1 && (
                            <button
                              onClick={() => handleSelectLayout(selectedSlide.id, selectedSlide.alt_layout_1!)}
                              className="block text-xs text-blue-600 hover:underline"
                            >
                              {selectedSlide.alt_layout_1.replace(/_/g, " ")}
                              {selectedSlide.alt_layout_1_rationale && (
                                <span className="text-slate-400 ml-1">— {selectedSlide.alt_layout_1_rationale}</span>
                              )}
                            </button>
                          )}
                          {selectedSlide.alt_layout_2 && (
                            <button
                              onClick={() => handleSelectLayout(selectedSlide.id, selectedSlide.alt_layout_2!)}
                              className="block text-xs text-blue-600 hover:underline"
                            >
                              {selectedSlide.alt_layout_2.replace(/_/g, " ")}
                              {selectedSlide.alt_layout_2_rationale && (
                                <span className="text-slate-400 ml-1">— {selectedSlide.alt_layout_2_rationale}</span>
                              )}
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                    <div className="p-3 rounded-lg border border-slate-200">
                      <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Visual</div>
                      <div className="text-sm font-medium text-slate-800">
                        {(selectedSlide.recommended_visual || "—").replace(/_/g, " ")}
                      </div>
                      {selectedSlide.recommended_chart && (
                        <div className="text-xs text-slate-500 mt-1">
                          Chart: {selectedSlide.recommended_chart.replace(/_/g, " ")}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Content Blocks */}
                  {selectedSlide.content_blocks_json && Array.isArray(selectedSlide.content_blocks_json) && selectedSlide.content_blocks_json.length > 0 && (
                    <div>
                      <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Content Blocks</div>
                      <div className="space-y-1.5">
                        {selectedSlide.content_blocks_json.map((block: any, idx: number) => (
                          <div key={idx} className="flex items-start gap-2 p-2 rounded border border-slate-100 bg-slate-50/50">
                            <span className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-slate-200 text-slate-600 shrink-0 mt-0.5">
                              {block.type}
                            </span>
                            <span className="text-xs text-slate-600 line-clamp-2">{block.content}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Evidence & Insights */}
                  <div className="grid grid-cols-2 gap-4">
                    <div className="p-3 rounded-lg border border-slate-200">
                      <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1">Evidence</div>
                      <div className="text-lg font-bold text-slate-800">
                        {Array.isArray(selectedSlide.evidence_ids_json) ? selectedSlide.evidence_ids_json.length : 0}
                      </div>
                      <div className="text-xs text-slate-500">supporting evidence items</div>
                    </div>
                    <div className="p-3 rounded-lg border border-slate-200">
                      <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1">Insights</div>
                      <div className="text-lg font-bold text-slate-800">
                        {Array.isArray(selectedSlide.insight_ids_json) ? selectedSlide.insight_ids_json.length : 0}
                      </div>
                      <div className="text-xs text-slate-500">approved insights</div>
                    </div>
                  </div>

                  {/* Confidence */}
                  {selectedSlide.confidence_json && typeof selectedSlide.confidence_json === "object" && (
                    <div className="p-3 rounded-lg border border-slate-200">
                      <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Confidence Scores</div>
                      <div className="space-y-2">
                        {[
                          { label: "Evidence Coverage", key: "evidence_coverage" },
                          { label: "Storyline Coverage", key: "storyline_coverage" },
                          { label: "Historical Layout Match", key: "historical_layout_match" },
                          { label: "Visual Suitability", key: "visual_suitability" },
                          { label: "Overall", key: "overall" },
                        ].map((item) => (
                          <div key={item.key}>
                            <div className="flex items-center justify-between text-xs text-slate-600 mb-0.5">
                              <span>{item.label}</span>
                            </div>
                            <ConfidenceBar
                              value={(selectedSlide.confidence_json as any)?.[item.key] || 0}
                              size={item.key === "overall" ? "lg" : "sm"}
                            />
                          </div>
                        ))}
                        {(selectedSlide.confidence_json as any)?.low_confidence_reasons && (
                          <div className="mt-2 p-2 rounded bg-amber-50 border border-amber-100">
                            <div className="text-[9px] font-semibold text-amber-600 uppercase mb-1">Low Confidence Reasons</div>
                            <ul className="text-xs text-amber-700 list-disc list-inside">
                              {((selectedSlide.confidence_json as any).low_confidence_reasons as string[]).map((r, i) => (
                                <li key={i}>{r}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Historical References */}
                  {selectedSlide.historical_refs_json && Array.isArray(selectedSlide.historical_refs_json) && selectedSlide.historical_refs_json.length > 0 && (
                    <div>
                      <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Historical References</div>
                      <div className="space-y-1">
                        {selectedSlide.historical_refs_json.map((ref: any, idx: number) => (
                          <div key={idx} className="flex items-center gap-3 p-2 rounded border border-slate-100 text-xs">
                            <span className="text-slate-400 font-mono">#{ref.slide_id}</span>
                            <span className="text-slate-600 flex-1 truncate">{ref.reason}</span>
                            <span className="text-emerald-600 font-medium">{Math.round(ref.similarity * 100)}%</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Speaker Notes */}
                  {selectedSlide.speaker_notes && (
                    <div>
                      <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Speaker Notes</div>
                      <p className="text-xs text-slate-500 leading-relaxed bg-slate-50 p-3 rounded-lg">
                        {selectedSlide.speaker_notes}
                      </p>
                    </div>
                  )}

                  {/* Transition */}
                  {selectedSlide.transition_to_next && (
                    <div className="p-3 rounded-lg bg-indigo-50 border border-indigo-100">
                      <div className="text-[9px] font-semibold text-indigo-500 uppercase tracking-wide mb-1">Transition to Next</div>
                      <p className="text-xs text-indigo-700 italic">{selectedSlide.transition_to_next}</p>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between pt-6">
        <button onClick={() => onNavigate("slide-intelligence")} className="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors">
          Back to Slide Intelligence
        </button>
        <button onClick={() => onNavigate("powerpoint-renderer")} className="px-5 py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm">
          Proceed to PowerPoint Renderer
        </button>
      </div>
    </div>
  );
}
