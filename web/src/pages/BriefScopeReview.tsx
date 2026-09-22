import { useState, useEffect, useCallback } from "react";
import { useProject, useActiveProjectId } from "../lib/project-context";
import { intelApi, type SpecResult, type SpecReadiness, type SpecClarification } from "../lib/intel-api";

export function BriefScopeReview({ onNavigate }: { onNavigate: (page: string) => void }) {
  const { activeProject } = useProject();
  const activeProjectId = useActiveProjectId();
  const [spec, setSpec] = useState<SpecResult | null>(null);
  const [readiness, setReadiness] = useState<SpecReadiness | null>(null);
  const [clarifications, setClarifications] = useState<SpecClarification[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [submitting, setSubmitting] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editFields, setEditFields] = useState({
    summary: "",
    geography: "",
    time_period: "",
    platforms: "",
    languages: "",
    methodology: "",
    competitors: "",
  });
  const [editingAnswer, setEditingAnswer] = useState<number | null>(null);
  const [editAnswerText, setEditAnswerText] = useState("");

  const loadSpec = useCallback(async () => {
    if (!activeProjectId) return;
    setLoading(true);
    setFetchError(null);
    try {
      const result = await intelApi.getSpec(activeProjectId);
      setSpec(result);
      setReadiness(result.readiness);
      setClarifications(result.clarifications || []);
    } catch {
      setSpec(null);
    } finally {
      setLoading(false);
    }
  }, [activeProjectId]);

  useEffect(() => { loadSpec(); }, [loadSpec]);

  const handleGenerate = async () => {
    if (!activeProjectId) return;
    setGenerating(true);
    try {
      const project = await intelApi.getProject(activeProjectId);
      const rawBrief = (project.spec as Record<string, unknown>)?.raw_brief as string || "";
      await intelApi.generateSpec(activeProjectId, rawBrief);
      await loadSpec();
    } catch (err) {
      setFetchError(err instanceof Error ? err.message : "Failed to generate specification");
    } finally {
      setGenerating(false);
    }
  };

  const handleSubmitAnswer = async (clarId: number) => {
    const answer = answers[clarId]?.trim();
    if (!answer) return;
    setSubmitting(clarId);
    try {
      await intelApi.resolveSpecClarification(clarId, answer);
      setAnswers(prev => { const next = { ...prev }; delete next[clarId]; return next; });
      await loadSpec();
    } catch {
    } finally {
      setSubmitting(null);
    }
  };

  const handleSkipQuestion = async (clarId: number) => {
    setSubmitting(clarId);
    try {
      await intelApi.resolveSpecClarification(clarId, "Skipped — use best judgment", "analyst");
      await loadSpec();
    } catch {
    } finally {
      setSubmitting(null);
    }
  };

  const startEditing = () => {
    if (!spec) return;
    const sections = spec.spec?.sections || {};
    const uc = sections.project_understanding?.content;
    const sc = sections.scope_dimensions?.content as Record<string, unknown> | undefined;
    const mc = sections.methodology?.content;
    const ec = sections.entities?.content;
    const competitors: string[] = [];
    if (Array.isArray(ec)) {
      for (const e of ec) {
        if (typeof e === "object" && e !== null && (e as Record<string, unknown>).type === "competitor") {
          competitors.push(String((e as Record<string, unknown>).name || ""));
        }
      }
    }
    setEditFields({
      summary: typeof uc === "string" ? uc : typeof uc === "object" && uc !== null ? Object.values(uc as Record<string, unknown>).filter(v => typeof v === "string").join("\n") : "",
      geography: sc?.geography ? String(sc.geography) : "",
      time_period: sc?.time_period ? String(sc.time_period) : "",
      platforms: sc?.platforms ? (Array.isArray(sc.platforms) ? sc.platforms.join(", ") : String(sc.platforms)) : "",
      languages: sc?.languages ? (Array.isArray(sc.languages) ? sc.languages.join(", ") : String(sc.languages)) : "",
      methodology: typeof mc === "string" ? mc : typeof mc === "object" && mc !== null ? (mc as Record<string, unknown>).primary ? String((mc as Record<string, unknown>).primary) : "" : "",
      competitors: competitors.join(", "),
    });
    setEditing(true);
  };

  const handleSaveEdits = async () => {
    if (!spec) return;
    setSaving(true);
    try {
      await intelApi.updateSpecSection(spec.id, "project_understanding", editFields.summary);
      const sc = (spec.spec?.sections?.scope_dimensions?.content || {}) as Record<string, unknown>;
      await intelApi.updateSpecSection(spec.id, "scope_dimensions", {
        ...sc,
        geography: editFields.geography,
        time_period: editFields.time_period,
        platforms: editFields.platforms,
        languages: editFields.languages,
      });
      const mc = spec.spec?.sections?.methodology?.content;
      const methObj = typeof mc === "object" && mc !== null ? mc as Record<string, unknown> : {};
      await intelApi.updateSpecSection(spec.id, "methodology", typeof mc === "string" ? editFields.methodology : { ...methObj, primary: editFields.methodology });

      const ec = spec.spec?.sections?.entities?.content;
      const existingEntities = Array.isArray(ec) ? ec as Record<string, unknown>[] : [];
      const nonCompetitors = existingEntities.filter(e => e.type !== "competitor");
      const newCompNames = editFields.competitors.split(",").map(s => s.trim()).filter(Boolean);
      const newCompEntities = newCompNames.map(name => ({ name, type: "competitor", confidence: "high", reasoning: "Manually added by analyst" }));
      await intelApi.updateSpecSection(spec.id, "entities", [...nonCompetitors, ...newCompEntities]);

      await loadSpec();
      setEditing(false);
    } catch (err) {
      setFetchError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleUpdateAnswer = async (clarId: number) => {
    const text = editAnswerText.trim();
    if (!text) return;
    setSubmitting(clarId);
    try {
      await intelApi.resolveSpecClarification(clarId, text);
      setEditingAnswer(null);
      setEditAnswerText("");
      await loadSpec();
    } catch {
    } finally {
      setSubmitting(null);
    }
  };

  const [saved, setSaved] = useState(false);

  const handleSaveSpec = async () => {
    if (!spec) return;
    try {
      await intelApi.approveSpec(spec.id);
      await loadSpec();
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      setFetchError(err instanceof Error ? err.message : "Save failed");
    }
  };

  const handleApproveSpec = async () => {
    if (!spec) return;
    try {
      await intelApi.approveSpec(spec.id);
      await loadSpec();
      setTimeout(() => onNavigate("background-research"), 600);
    } catch (err) {
      setFetchError(err instanceof Error ? err.message : "Approval failed");
    }
  };

  const handleDownloadDocx = async () => {
    if (!spec) return;
    setDownloading(true);
    try {
      await intelApi.renderSpecDocx(spec.id);
      const blob = await intelApi.downloadSpecDocx(spec.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Research_Specification_${activeProject?.name || "spec"}.docx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
    } finally {
      setDownloading(false);
    }
  };

  // ── Early returns ──

  if (!activeProjectId) {
    return (
      <div className="p-8 max-w-3xl mx-auto animate-fade-in">
        <h1 className="text-xl font-semibold text-slate-900">Brief & Scope</h1>
        <div className="mt-8 bg-amber-50 border border-amber-200 rounded-xl p-6">
          <p className="text-sm text-amber-800">No active project. Create one first.</p>
          <button onClick={() => onNavigate("new-project")} className="mt-3 px-4 py-2.5 text-sm font-medium bg-[#5B2C9D] text-white rounded-lg hover:opacity-90 transition-colors shadow-sm">
            Create Project
          </button>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="p-8 max-w-3xl mx-auto animate-fade-in">
        <h1 className="text-xl font-semibold text-slate-900">Brief & Scope</h1>
        <p className="text-sm text-slate-500 mt-0.5">{activeProject?.name}</p>
        <div className="mt-12 flex items-center justify-center py-16">
          <div className="flex items-center gap-3 text-sm text-slate-500">
            <svg className="animate-spin h-5 w-5 text-[#5B2C9D]" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Loading...
          </div>
        </div>
      </div>
    );
  }

  if (!spec) {
    return (
      <div className="p-8 max-w-3xl mx-auto animate-fade-in">
        <h1 className="text-xl font-semibold text-slate-900">Brief & Scope</h1>
        <p className="text-sm text-slate-500 mt-0.5">{activeProject?.name}</p>
        <div className="mt-8 bg-white border border-slate-200 rounded-xl p-8 text-center shadow-sm">
          <h2 className="text-base font-semibold text-slate-900">Analyze your brief</h2>
          <p className="text-sm text-slate-500 mt-2 max-w-sm mx-auto">
            We'll read your brief, extract scope, objectives, and entities, then ask you to confirm a few details.
          </p>
          {fetchError && <p className="text-sm text-red-600 mt-3">{fetchError}</p>}
          <button
            disabled={generating}
            onClick={handleGenerate}
            className="mt-5 px-5 py-2.5 text-sm font-medium text-white rounded-lg shadow-sm transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ backgroundColor: "#5B2C9D" }}
          >
            {generating ? "Analyzing..." : "Analyze Brief"}
          </button>
        </div>
      </div>
    );
  }

  // ── Main render — spec loaded ──

  const sections = spec.spec?.sections || {};
  const isApproved = spec.approval_status === "approved";

  // Extract the summary from project_understanding section
  const understandingContent = sections.project_understanding?.content;
  let summaryText = "";
  if (typeof understandingContent === "string") {
    summaryText = understandingContent.split("\n").filter(l => l.trim()).slice(0, 3).join(" ");
  } else if (typeof understandingContent === "object" && understandingContent !== null && !Array.isArray(understandingContent)) {
    const vals = Object.values(understandingContent as Record<string, unknown>);
    summaryText = vals.filter(v => typeof v === "string").slice(0, 2).join(" ");
  }
  if (summaryText.length > 400) summaryText = summaryText.slice(0, 397) + "...";

  // Extract key metadata from scope section
  const scopeContent = sections.scope_dimensions?.content;
  const metaItems: { label: string; value: string }[] = [];
  if (typeof scopeContent === "object" && scopeContent !== null && !Array.isArray(scopeContent)) {
    const sc = scopeContent as Record<string, unknown>;
    if (sc.geography) metaItems.push({ label: "Geography", value: String(sc.geography) });
    if (sc.time_period) metaItems.push({ label: "Time Period", value: String(sc.time_period) });
    if (sc.platforms) metaItems.push({ label: "Platforms", value: Array.isArray(sc.platforms) ? sc.platforms.join(", ") : String(sc.platforms) });
    if (sc.languages) metaItems.push({ label: "Languages", value: Array.isArray(sc.languages) ? sc.languages.join(", ") : String(sc.languages) });
  }
  const methodContent = sections.methodology?.content;
  if (typeof methodContent === "object" && methodContent !== null && !Array.isArray(methodContent)) {
    const mc = methodContent as Record<string, unknown>;
    if (mc.primary) metaItems.push({ label: "Methodology", value: String(mc.primary) });
  } else if (typeof methodContent === "string" && methodContent.trim()) {
    metaItems.push({ label: "Methodology", value: methodContent.split("\n")[0] });
  }

  // Split clarifications
  const unresolvedBlocking = clarifications.filter(c => c.is_blocking && !c.resolved_at);
  const unresolvedAdvisory = clarifications.filter(c => !c.is_blocking && !c.resolved_at);
  const resolved = clarifications.filter(c => c.resolved_at);
  const allResolved = unresolvedBlocking.length === 0 && unresolvedAdvisory.length === 0;

  const renderQuestion = (c: SpecClarification, idx: number, isBlocking: boolean) => (
    <div key={c.id} className="py-4 border-b border-slate-100 last:border-0">
      <div className="flex items-start gap-3">
        <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold shrink-0 mt-0.5 ${isBlocking ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"}`}>
          {idx + 1}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm text-slate-800 leading-relaxed">{c.question}</p>
          <div className="mt-2.5 flex gap-2">
            <input
              type="text"
              value={answers[c.id] || ""}
              onChange={(e) => setAnswers(prev => ({ ...prev, [c.id]: e.target.value }))}
              onKeyDown={(e) => e.key === "Enter" && handleSubmitAnswer(c.id)}
              placeholder="Type your answer..."
              className="flex-1 border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-900 placeholder:text-slate-300 focus:outline-none focus:ring-2 focus:ring-[#5B2C9D]/20 focus:border-[#5B2C9D]/40 transition-all"
            />
            <button
              onClick={() => handleSubmitAnswer(c.id)}
              disabled={!answers[c.id]?.trim() || submitting === c.id}
              className="px-3 py-2 text-xs font-medium text-white rounded-lg transition-all disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
              style={{ backgroundColor: "#5B2C9D" }}
            >
              {submitting === c.id ? "..." : "Submit"}
            </button>
            <button
              onClick={() => handleSkipQuestion(c.id)}
              disabled={submitting === c.id}
              className="px-3 py-2 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50 transition-all disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
            >
              Skip
            </button>
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <div className="p-8 max-w-3xl mx-auto space-y-5 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Brief & Scope</h1>
          <p className="text-sm text-slate-500 mt-0.5">{activeProject?.name}</p>
        </div>
        <div className="flex items-center gap-2">
          {isApproved && <span className="text-xs font-semibold text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-full border border-emerald-100">Approved</span>}
          <button
            onClick={handleDownloadDocx}
            disabled={downloading}
            className="text-xs font-medium text-[#5B2C9D] border border-[#5B2C9D]/20 px-3 py-1.5 rounded-lg hover:bg-[#5B2C9D]/5 transition-colors disabled:opacity-40"
          >
            {downloading ? "Exporting..." : "Export Full Spec"}
          </button>
        </div>
      </div>

      {fetchError && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">{fetchError}</div>
      )}

      {/* What we understood */}
      {(summaryText || editing) && (
        <div className="bg-slate-50 border border-slate-200 rounded-xl p-5">
          <div className="flex items-center justify-between mb-2">
            <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">What we understood</div>
            {!editing ? (
              <button
                onClick={startEditing}
                className="flex items-center gap-1 text-[11px] font-medium text-[#5B2C9D] hover:text-[#5B2C9D]/80 transition-colors"
              >
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
                  <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
                </svg>
                Edit
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setEditing(false)}
                  className="text-[11px] font-medium text-slate-400 hover:text-slate-600 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSaveEdits}
                  disabled={saving}
                  className="flex items-center gap-1 text-[11px] font-medium text-white px-3 py-1 rounded-md transition-all disabled:opacity-50"
                  style={{ backgroundColor: "#5B2C9D" }}
                >
                  {saving ? "Saving..." : "Save Changes"}
                </button>
              </div>
            )}
          </div>

          {!editing ? (() => {
            const ec = spec?.spec?.sections?.entities?.content;
            const compNames = Array.isArray(ec) ? (ec as Record<string, unknown>[]).filter(e => e.type === "competitor").map(e => String(e.name)) : [];
            return (
              <>
                <p className="text-sm text-slate-700 leading-relaxed">{summaryText}</p>
                {(metaItems.length > 0 || compNames.length > 0) && (
                  <div className="flex flex-wrap gap-x-5 gap-y-1.5 mt-3 pt-3 border-t border-slate-200">
                    {metaItems.map((m) => (
                      <div key={m.label} className="text-xs text-slate-500">
                        <span className="font-semibold text-slate-600">{m.label}:</span> {m.value}
                      </div>
                    ))}
                    {compNames.length > 0 && (
                      <div className="text-xs text-slate-500">
                        <span className="font-semibold text-slate-600">Competitors:</span> {compNames.join(", ")}
                      </div>
                    )}
                  </div>
                )}
              </>
            );
          })() : (
            <div className="space-y-3">
              <div>
                <label className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Summary</label>
                <textarea
                  value={editFields.summary}
                  onChange={(e) => setEditFields(f => ({ ...f, summary: e.target.value }))}
                  rows={4}
                  className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-800 bg-white focus:outline-none focus:ring-2 focus:ring-[#5B2C9D]/20 focus:border-[#5B2C9D]/40 resize-y"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                {([
                  { key: "geography", label: "Geography" },
                  { key: "time_period", label: "Time Period" },
                  { key: "platforms", label: "Platforms" },
                  { key: "languages", label: "Languages" },
                ] as const).map(({ key, label }) => (
                  <div key={key}>
                    <label className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">{label}</label>
                    <input
                      type="text"
                      value={editFields[key]}
                      onChange={(e) => setEditFields(f => ({ ...f, [key]: e.target.value }))}
                      className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-800 bg-white focus:outline-none focus:ring-2 focus:ring-[#5B2C9D]/20 focus:border-[#5B2C9D]/40"
                    />
                  </div>
                ))}
              </div>
              <div>
                <label className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Competitors</label>
                <input
                  type="text"
                  value={editFields.competitors}
                  onChange={(e) => setEditFields(f => ({ ...f, competitors: e.target.value }))}
                  placeholder="e.g. Archer, Think, Jack Links, Tillamook"
                  className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-800 bg-white focus:outline-none focus:ring-2 focus:ring-[#5B2C9D]/20 focus:border-[#5B2C9D]/40"
                />
                <p className="text-[10px] text-slate-400 mt-1">Comma-separated list of competitor brands to track</p>
              </div>
              <div>
                <label className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Methodology</label>
                <textarea
                  value={editFields.methodology}
                  onChange={(e) => setEditFields(f => ({ ...f, methodology: e.target.value }))}
                  rows={3}
                  className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-800 bg-white focus:outline-none focus:ring-2 focus:ring-[#5B2C9D]/20 focus:border-[#5B2C9D]/40 resize-y"
                />
              </div>
            </div>
          )}
        </div>
      )}

      {/* Questions that need answers */}
      {!isApproved && unresolvedBlocking.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm">
          <div className="px-5 pt-5 pb-2">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-red-500" />
              <h2 className="text-sm font-semibold text-slate-900">We need a few details</h2>
              <button
                onClick={async () => {
                  for (const c of unresolvedBlocking) await handleSkipQuestion(c.id);
                }}
                disabled={submitting !== null}
                className="ml-auto text-xs font-medium text-slate-400 hover:text-slate-600 transition-colors disabled:opacity-40"
              >
                Skip all
              </button>
            </div>
            <p className="text-xs text-slate-500 mt-1 ml-4">Answer these or skip to proceed.</p>
          </div>
          <div className="px-5 pb-3">
            {unresolvedBlocking.map((c, i) => renderQuestion(c, i, true))}
          </div>
        </div>
      )}

      {!isApproved && unresolvedAdvisory.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm">
          <div className="px-5 pt-5 pb-2">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-amber-400" />
              <h2 className="text-sm font-semibold text-slate-900">Optional clarifications</h2>
              <button
                onClick={async () => {
                  for (const c of unresolvedAdvisory) await handleSkipQuestion(c.id);
                }}
                disabled={submitting !== null}
                className="ml-auto text-xs font-medium text-slate-400 hover:text-slate-600 transition-colors disabled:opacity-40"
              >
                Skip all
              </button>
            </div>
            <p className="text-xs text-slate-500 mt-1 ml-4">Answering these improves research quality, but you can skip them.</p>
          </div>
          <div className="px-5 pb-3">
            {unresolvedAdvisory.map((c, i) => renderQuestion(c, i, false))}
          </div>
        </div>
      )}

      {/* Answered questions (collapsed) */}
      {resolved.length > 0 && (
        <details className="group">
          <summary className="text-xs font-medium text-slate-400 cursor-pointer hover:text-slate-600 transition-colors list-none flex items-center gap-1.5">
            <svg className="w-3.5 h-3.5 transition-transform group-open:rotate-90" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
            {resolved.length} answered
          </summary>
          <div className="mt-2 bg-white border border-slate-200 rounded-xl shadow-sm px-5 py-2">
            {resolved.map((c) => (
              <div key={c.id} className="py-3 border-b border-slate-50 last:border-0">
                <p className="text-sm text-slate-500">{c.question}</p>
                {editingAnswer === c.id ? (
                  <div className="mt-1.5 flex gap-2">
                    <input
                      type="text"
                      value={editAnswerText}
                      onChange={(e) => setEditAnswerText(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleUpdateAnswer(c.id)}
                      className="flex-1 border border-slate-200 rounded-lg px-3 py-1.5 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#5B2C9D]/20 focus:border-[#5B2C9D]/40"
                    />
                    <button
                      onClick={() => handleUpdateAnswer(c.id)}
                      disabled={!editAnswerText.trim() || submitting === c.id}
                      className="px-3 py-1.5 text-xs font-medium text-white rounded-lg disabled:opacity-40"
                      style={{ backgroundColor: "#5B2C9D" }}
                    >
                      {submitting === c.id ? "..." : "Save"}
                    </button>
                    <button
                      onClick={() => { setEditingAnswer(null); setEditAnswerText(""); }}
                      className="px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <div className="flex items-start justify-between mt-1 group/answer">
                    <p className="text-sm text-slate-800 pl-3 border-l-2 border-emerald-300">{c.answer}</p>
                    <button
                      onClick={() => { setEditingAnswer(c.id); setEditAnswerText(c.answer || ""); }}
                      className="opacity-0 group-hover/answer:opacity-100 ml-2 text-[11px] font-medium text-[#5B2C9D] hover:text-[#5B2C9D]/80 transition-all shrink-0"
                    >
                      Edit
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Ready state / Approval */}
      {!isApproved && allResolved && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-5 text-center">
          <div className="text-sm font-semibold text-emerald-800">All clear — ready to proceed</div>
          <p className="text-xs text-emerald-600 mt-1">The research specification is complete. Approve to begin background research.</p>
        </div>
      )}

      {!isApproved && (
        <div className="flex items-center justify-between pt-2">
          <button onClick={() => onNavigate("new-project")} className="text-sm text-slate-400 hover:text-slate-600 transition-colors">
            Back to Projects
          </button>
          <div className="flex items-center gap-3">
            <button
              onClick={handleSaveSpec}
              disabled={unresolvedBlocking.length > 0}
              className="px-4 py-2.5 text-sm font-medium rounded-lg border transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ color: "#5B2C9D", borderColor: "rgba(91,44,157,0.25)" }}
            >
              {saved ? "Saved!" : "Save"}
            </button>
            <button
              onClick={handleApproveSpec}
              disabled={unresolvedBlocking.length > 0}
              className="px-5 py-2.5 text-sm font-medium text-white rounded-lg transition-all shadow-sm disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ backgroundColor: "#5B2C9D" }}
            >
              {unresolvedBlocking.length > 0 ? `${unresolvedBlocking.length} questions remaining` : "Approve & Proceed"}
            </button>
          </div>
        </div>
      )}

      {isApproved && (
        <div className="flex items-center justify-between pt-2">
          <button onClick={() => onNavigate("new-project")} className="text-sm text-slate-400 hover:text-slate-600 transition-colors">
            Back to Projects
          </button>
          <button
            onClick={() => onNavigate("background-research")}
            className="px-5 py-2.5 text-sm font-medium text-white rounded-lg transition-all shadow-sm"
            style={{ backgroundColor: "#5B2C9D" }}
          >
            Proceed to Background Research
          </button>
        </div>
      )}
    </div>
  );
}
