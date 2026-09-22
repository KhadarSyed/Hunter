import { useState, useEffect, useCallback } from "react";
import { intelApi } from "../lib/intel-api";
import { useActiveProjectId } from "../lib/project-context";
import type {
  PCPresentation,
  PCSlide,
  PCPresentationDetail,
  RenderJob,
  RenderResult,
  RenderSummary,
  RenderTheme,
  RenderValidation,
  RenderMetric,
  RenderHistory,
} from "../data/contracts";

interface Props {
  onNavigate: (page: string) => void;
}

export function PowerPointRendererPage({ onNavigate }: Props) {
  const projectId = useActiveProjectId() ?? 1;
  const [presentations, setPresentations] = useState<PCPresentation[]>([]);
  const [selectedPresId, setSelectedPresId] = useState<number | null>(null);
  const [detail, setDetail] = useState<PCPresentationDetail | null>(null);
  const [summary, setSummary] = useState<RenderSummary | null>(null);
  const [themes, setThemes] = useState<RenderTheme[]>([]);
  const [selectedTheme, setSelectedTheme] = useState("hunter_default");
  const [validation, setValidation] = useState<RenderValidation | null>(null);
  const [renderResult, setRenderResult] = useState<RenderResult | null>(null);
  const [rendering, setRendering] = useState(false);
  const [renderProgress, setRenderProgress] = useState(0);
  const [renderMessage, setRenderMessage] = useState("");
  const [metrics, setMetrics] = useState<RenderMetric[]>([]);
  const [history, setHistory] = useState<RenderHistory[]>([]);
  const [selectedSlide, setSelectedSlide] = useState<PCSlide | null>(null);
  const [activeTab, setActiveTab] = useState<"slides" | "metrics" | "history">("slides");
  const [error, setError] = useState("");

  const loadPresentations = useCallback(async () => {
    try {
      const list = await intelApi.composerList(projectId);
      setPresentations(list);
      const approved = list.find((p) => p.status === "approved");
      if (approved) {
        setSelectedPresId(approved.id);
      } else if (list.length > 0) {
        setSelectedPresId(list[0].id);
      }
    } catch {
      setPresentations([]);
    }
  }, [projectId]);

  const loadDetail = useCallback(async () => {
    if (!selectedPresId) return;
    try {
      const d = await intelApi.composerDetail(selectedPresId);
      setDetail(d);
    } catch {
      setDetail(null);
    }
  }, [selectedPresId]);

  const loadRenderSummary = useCallback(async () => {
    if (!selectedPresId) return;
    try {
      const s = await intelApi.rendererSummary(selectedPresId);
      setSummary(s);
    } catch {
      setSummary(null);
    }
  }, [selectedPresId]);

  const loadThemes = useCallback(async () => {
    try {
      const t = await intelApi.rendererThemes();
      setThemes(t);
    } catch {
      setThemes([]);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    if (!selectedPresId) return;
    try {
      const h = await intelApi.rendererHistory(selectedPresId);
      setHistory(h);
    } catch {
      setHistory([]);
    }
  }, [selectedPresId]);

  useEffect(() => {
    loadPresentations();
    loadThemes();
  }, [loadPresentations, loadThemes]);

  useEffect(() => {
    loadDetail();
    loadRenderSummary();
    loadHistory();
    setValidation(null);
    setRenderResult(null);
    setMetrics([]);
    setSelectedSlide(null);
  }, [selectedPresId, loadDetail, loadRenderSummary, loadHistory]);

  const handleValidate = async () => {
    if (!selectedPresId) return;
    try {
      const v = await intelApi.rendererValidate(selectedPresId);
      setValidation(v);
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleRender = async () => {
    if (!selectedPresId) return;
    setRendering(true);
    setRenderProgress(0);
    setRenderMessage("Starting render...");
    setError("");
    setRenderResult(null);
    try {
      const result = await intelApi.rendererRender(selectedPresId, selectedTheme);
      setRenderResult(result);
      setRenderProgress(100);
      setRenderMessage("Render complete");
      loadRenderSummary();
      loadHistory();
      if (result.job_id) {
        try {
          const m = await intelApi.rendererMetrics(result.job_id);
          setMetrics(m);
        } catch {}
      }
    } catch (e: any) {
      setError(e.message);
      setRenderMessage("Render failed");
    } finally {
      setRendering(false);
    }
  };

  const handleRenderSlide = async (slideId: number) => {
    setRendering(true);
    setError("");
    try {
      const result = await intelApi.rendererRenderSlide(slideId, selectedTheme);
      setRenderResult(result);
      loadRenderSummary();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setRendering(false);
    }
  };

  const handleDownload = () => {
    if (!renderResult?.job_id && !summary?.latest_job?.id) return;
    const jobId = renderResult?.job_id || summary?.latest_job?.id;
    if (jobId) {
      window.open(intelApi.rendererDownloadUrl(jobId), "_blank");
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const formatMs = (ms: number) => {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  const purposeColor: Record<string, string> = {
    cover: "bg-violet-100 text-violet-700",
    agenda: "bg-blue-100 text-blue-700",
    executive_summary: "bg-amber-100 text-amber-700",
    conclusion: "bg-emerald-100 text-emerald-700",
    appendix: "bg-slate-100 text-slate-600",
    key_finding: "bg-indigo-100 text-indigo-700",
    trend: "bg-cyan-100 text-cyan-700",
    theme: "bg-purple-100 text-purple-700",
    competitive: "bg-orange-100 text-orange-700",
    recommendation: "bg-green-100 text-green-700",
    risk: "bg-red-100 text-red-700",
    opportunity: "bg-teal-100 text-teal-700",
  };

  if (presentations.length === 0) {
    return (
      <div className="p-8">
        <div className="flex items-center gap-3 mb-6">
          <h1 className="text-xl font-semibold text-slate-900">PowerPoint Renderer</h1>
          <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-violet-100 text-violet-700">STAGE 11</span>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-12 text-center">
          <p className="text-slate-500 mb-4">No presentations found. Generate a presentation in the Composer first.</p>
          <button onClick={() => onNavigate("presentation-composer")} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700">
            Go to Presentation Composer
          </button>
        </div>
        <div className="flex items-center justify-between pt-6">
          <button onClick={() => onNavigate("presentation-composer")} className="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors">
            Back to Presentation Composer
          </button>
          <button onClick={() => onNavigate("word-renderer")} className="px-5 py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm">
            Proceed to Word Report
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold text-slate-900">PowerPoint Renderer</h1>
          <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-violet-100 text-violet-700">STAGE 11</span>
        </div>
        <div className="flex items-center gap-3">
          {presentations.length > 1 && (
            <select
              value={selectedPresId ?? ""}
              onChange={(e) => setSelectedPresId(Number(e.target.value))}
              className="text-sm border border-slate-200 rounded-lg px-3 py-1.5"
            >
              {presentations.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title} ({p.status})
                </option>
              ))}
            </select>
          )}
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-5 gap-4">
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="text-[11px] text-slate-400 font-medium mb-1">Total Slides</div>
          <div className="text-2xl font-bold text-slate-900">{detail?.slides.length ?? 0}</div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="text-[11px] text-slate-400 font-medium mb-1">Status</div>
          <div className="text-lg font-semibold text-slate-900 capitalize">{detail?.presentation.status ?? "—"}</div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="text-[11px] text-slate-400 font-medium mb-1">Renders</div>
          <div className="text-2xl font-bold text-slate-900">{summary?.total_renders ?? 0}</div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="text-[11px] text-slate-400 font-medium mb-1">Latest File</div>
          <div className="text-sm font-medium text-slate-900">
            {summary?.latest_render ? formatBytes(summary.latest_render.output_size_bytes) : "—"}
          </div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="text-[11px] text-slate-400 font-medium mb-1">Render Time</div>
          <div className="text-sm font-medium text-slate-900">
            {summary?.latest_render ? formatMs(summary.latest_render.render_duration_ms) : "—"}
          </div>
        </div>
      </div>

      {/* Render controls */}
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-slate-900">Render Controls</h2>
          <div className="flex items-center gap-3">
            <select
              value={selectedTheme}
              onChange={(e) => setSelectedTheme(e.target.value)}
              className="text-sm border border-slate-200 rounded-lg px-3 py-1.5"
            >
              {themes.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
              {themes.length === 0 && <option value="hunter_default">Hunter PR Default</option>}
            </select>
            <button
              onClick={handleValidate}
              className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg hover:bg-slate-50"
            >
              Validate
            </button>
            <button
              onClick={handleRender}
              disabled={rendering}
              className="px-4 py-1.5 text-sm bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50"
            >
              {rendering ? "Rendering..." : "Render Presentation"}
            </button>
            {(summary?.has_download || renderResult?.job_id) && (
              <button
                onClick={handleDownload}
                className="px-4 py-1.5 text-sm bg-emerald-600 text-white rounded-lg font-medium hover:bg-emerald-700"
              >
                Download .pptx
              </button>
            )}
          </div>
        </div>

        {/* Progress bar */}
        {rendering && (
          <div className="mb-4">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-slate-500">{renderMessage}</span>
              <span className="text-xs font-medium text-slate-600">{renderProgress}%</span>
            </div>
            <div className="w-full bg-slate-100 rounded-full h-2">
              <div
                className="bg-blue-600 h-2 rounded-full transition-all"
                style={{ width: `${renderProgress}%` }}
              />
            </div>
          </div>
        )}

        {/* Validation result */}
        {validation && (
          <div className={`rounded-lg p-3 text-sm ${validation.valid ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>
            <div className="font-medium mb-1">{validation.valid ? "Valid for rendering" : "Validation failed"}</div>
            {validation.issues.length > 0 && (
              <ul className="list-disc list-inside space-y-0.5">
                {validation.issues.map((issue, i) => <li key={i}>{issue}</li>)}
              </ul>
            )}
            {validation.warnings.length > 0 && (
              <ul className="list-disc list-inside space-y-0.5 text-amber-600 mt-1">
                {validation.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            )}
          </div>
        )}

        {/* Render result */}
        {renderResult && !rendering && (
          <div className={`rounded-lg p-3 text-sm ${renderResult.status === "completed" ? "bg-emerald-50" : "bg-red-50"}`}>
            {renderResult.status === "completed" ? (
              <div className="text-emerald-700">
                <span className="font-medium">Render complete</span>
                {" — "}{renderResult.slide_count} slides, {formatBytes(renderResult.file_size_bytes ?? 0)}, {formatMs(renderResult.render_duration_ms ?? 0)}
                {(renderResult.warnings?.length ?? 0) > 0 && (
                  <div className="mt-1 text-amber-600">
                    {renderResult.warnings?.map((w, i) => <div key={i}>{w}</div>)}
                  </div>
                )}
              </div>
            ) : (
              <div className="text-red-700">{renderResult.error || "Render failed"}</div>
            )}
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="rounded-lg p-3 text-sm bg-red-50 text-red-700 mt-2">{error}</div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-slate-100 rounded-lg p-0.5 w-fit">
        {(["slides", "metrics", "history"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-1.5 text-sm rounded-md capitalize ${activeTab === tab ? "bg-white font-medium text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"}`}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="flex gap-6">
        {/* Slide list / Metrics / History */}
        <div className="flex-1 min-w-0">
          {activeTab === "slides" && detail && (
            <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-900">Slide Navigator</h3>
                <span className="text-xs text-slate-400">{detail.slides.length} slides</span>
              </div>
              <div className="divide-y divide-slate-50">
                {detail.slides.map((slide, idx) => (
                  <button
                    key={slide.id}
                    onClick={() => setSelectedSlide(slide)}
                    className={`w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-slate-50 transition-colors ${selectedSlide?.id === slide.id ? "bg-blue-50" : ""}`}
                  >
                    <span className="text-xs font-mono text-slate-400 w-6 text-right">{idx + 1}</span>
                    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${purposeColor[slide.slide_purpose] || "bg-slate-100 text-slate-600"}`}>
                      {slide.slide_purpose.replace(/_/g, " ")}
                    </span>
                    <span className="text-sm text-slate-700 truncate flex-1">{slide.title}</span>
                    <span className="text-xs text-slate-400">{slide.recommended_visual?.replace(/_/g, " ") || "text"}</span>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleRenderSlide(slide.id); }}
                      className="text-[10px] px-2 py-0.5 rounded border border-slate-200 text-slate-500 hover:bg-slate-100"
                      title="Render this slide only"
                    >
                      Render
                    </button>
                  </button>
                ))}
              </div>
            </div>
          )}

          {activeTab === "metrics" && (
            <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-100">
                <h3 className="text-sm font-semibold text-slate-900">Render Metrics</h3>
              </div>
              {metrics.length === 0 ? (
                <div className="p-8 text-center text-sm text-slate-400">
                  No metrics yet. Render a presentation first.
                </div>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-slate-50 text-slate-500 text-xs">
                      <th className="px-4 py-2 text-left font-medium">#</th>
                      <th className="px-4 py-2 text-left font-medium">Slide</th>
                      <th className="px-4 py-2 text-left font-medium">Type</th>
                      <th className="px-4 py-2 text-right font-medium">Duration</th>
                      <th className="px-4 py-2 text-right font-medium">Warnings</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-50">
                    {metrics.map((m) => (
                      <tr key={m.id} className="hover:bg-slate-50">
                        <td className="px-4 py-2 text-slate-400 font-mono">{m.slide_number + 1}</td>
                        <td className="px-4 py-2 text-slate-700">Slide {m.slide_id}</td>
                        <td className="px-4 py-2 text-slate-500 capitalize">{m.render_type}</td>
                        <td className="px-4 py-2 text-right text-slate-600">{formatMs(m.duration_ms)}</td>
                        <td className="px-4 py-2 text-right text-slate-400">{m.warnings_json?.length || 0}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {activeTab === "history" && (
            <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-100">
                <h3 className="text-sm font-semibold text-slate-900">Render History</h3>
              </div>
              {history.length === 0 ? (
                <div className="p-8 text-center text-sm text-slate-400">
                  No render history yet.
                </div>
              ) : (
                <div className="divide-y divide-slate-50">
                  {history.map((h) => (
                    <div key={h.id} className="px-4 py-3 flex items-center gap-3">
                      <span className={`text-[10px] font-medium px-2 py-0.5 rounded ${
                        h.action.includes("completed") ? "bg-emerald-100 text-emerald-700" :
                        h.action.includes("failed") ? "bg-red-100 text-red-700" :
                        "bg-blue-100 text-blue-700"
                      }`}>{h.action.replace(/_/g, " ")}</span>
                      <span className="text-xs text-slate-500 flex-1">
                        {h.details_json?.slide_count && `${h.details_json.slide_count} slides`}
                        {h.details_json?.duration_ms && ` in ${formatMs(h.details_json.duration_ms)}`}
                        {h.details_json?.file_size && ` (${formatBytes(h.details_json.file_size)})`}
                        {h.details_json?.error && h.details_json.error}
                      </span>
                      <span className="text-xs text-slate-400">{h.actor}</span>
                      <span className="text-xs text-slate-300">{new Date(h.created_at * 1000).toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Slide inspector */}
        {selectedSlide && activeTab === "slides" && (
          <div className="w-96 shrink-0 bg-white rounded-xl border border-slate-200 p-4 space-y-4 max-h-[70vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-900">Slide Inspector</h3>
              <button onClick={() => setSelectedSlide(null)} className="text-xs text-slate-400 hover:text-slate-600">Close</button>
            </div>

            <div>
              <div className="text-[10px] text-slate-400 font-medium mb-0.5">Title</div>
              <div className="text-sm text-slate-800 font-medium">{selectedSlide.title}</div>
            </div>

            {selectedSlide.subtitle && (
              <div>
                <div className="text-[10px] text-slate-400 font-medium mb-0.5">Subtitle</div>
                <div className="text-sm text-slate-600">{selectedSlide.subtitle}</div>
              </div>
            )}

            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="text-[10px] text-slate-400 font-medium mb-0.5">Purpose</div>
                <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${purposeColor[selectedSlide.slide_purpose] || "bg-slate-100 text-slate-600"}`}>
                  {selectedSlide.slide_purpose.replace(/_/g, " ")}
                </span>
              </div>
              <div>
                <div className="text-[10px] text-slate-400 font-medium mb-0.5">Visual</div>
                <div className="text-xs text-slate-600">{selectedSlide.recommended_visual?.replace(/_/g, " ") || "—"}</div>
              </div>
              <div>
                <div className="text-[10px] text-slate-400 font-medium mb-0.5">Layout</div>
                <div className="text-xs text-slate-600">{selectedSlide.layout_recommendation || "—"}</div>
              </div>
              <div>
                <div className="text-[10px] text-slate-400 font-medium mb-0.5">Confidence</div>
                <div className="flex items-center gap-1">
                  <div className="w-16 h-1.5 bg-slate-100 rounded-full">
                    <div
                      className="h-1.5 rounded-full bg-blue-500"
                      style={{ width: `${(selectedSlide.overall_confidence ?? 0) * 100}%` }}
                    />
                  </div>
                  <span className="text-[10px] text-slate-500">{Math.round((selectedSlide.overall_confidence ?? 0) * 100)}%</span>
                </div>
              </div>
            </div>

            {selectedSlide.key_message && (
              <div>
                <div className="text-[10px] text-slate-400 font-medium mb-0.5">Key Message</div>
                <div className="text-xs text-slate-600 bg-violet-50 rounded p-2">{selectedSlide.key_message}</div>
              </div>
            )}

            {selectedSlide.narrative && (
              <div>
                <div className="text-[10px] text-slate-400 font-medium mb-0.5">Narrative</div>
                <div className="text-xs text-slate-600 leading-relaxed">{selectedSlide.narrative}</div>
              </div>
            )}

            <div>
              <div className="text-[10px] text-slate-400 font-medium mb-0.5">Content Blocks</div>
              <div className="space-y-1">
                {(selectedSlide.content_blocks_json || []).map((block, i) => (
                  <div key={i} className="text-[10px] flex gap-2 items-start">
                    <span className="bg-slate-100 text-slate-500 px-1 py-0.5 rounded font-mono shrink-0">{block.type}</span>
                    <span className="text-slate-600 truncate">{block.content}</span>
                  </div>
                ))}
                {(!selectedSlide.content_blocks_json || selectedSlide.content_blocks_json.length === 0) && (
                  <span className="text-[10px] text-slate-300">No content blocks</span>
                )}
              </div>
            </div>

            {selectedSlide.speaker_notes && (
              <div>
                <div className="text-[10px] text-slate-400 font-medium mb-0.5">Speaker Notes</div>
                <div className="text-[10px] text-slate-500 italic bg-slate-50 rounded p-2">{selectedSlide.speaker_notes}</div>
              </div>
            )}

            <div className="pt-2 border-t border-slate-100">
              <button
                onClick={() => handleRenderSlide(selectedSlide.id)}
                disabled={rendering}
                className="w-full px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50"
              >
                Render This Slide
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Navigation */}
      <div className="flex items-center justify-between pt-6">
        <button onClick={() => onNavigate("presentation-composer")} className="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors">
          Back to Presentation Composer
        </button>
        <button onClick={() => onNavigate("word-renderer")} className="px-5 py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm">
          Proceed to Word Report
        </button>
      </div>
    </div>
  );
}
