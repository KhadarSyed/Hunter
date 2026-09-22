import { useState } from "react";
import { useDemoState } from "../lib/demo-state";
import { useProject } from "../lib/project-context";

function Card({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-white border border-slate-200 rounded-xl shadow-sm ${className}`}>
      <div className="px-5 py-3.5 border-b border-slate-100">
        <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide">{title}</h3>
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

function ScoreBar({ label, value, invert }: { label: string; value: number; invert?: boolean }) {
  const color = invert
    ? value <= 10 ? "bg-emerald-500" : value <= 25 ? "bg-amber-500" : "bg-red-500"
    : value >= 75 ? "bg-emerald-500" : value >= 50 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-slate-500 w-40 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(value, 100)}%` }} />
      </div>
      <span className="text-xs font-semibold text-slate-700 tabular-nums w-10 text-right">{value}%</span>
    </div>
  );
}

const DEMO_SAMPLE_RECORDS = [
  { id: 1, headline: "Consumer shares weekly meal prep routine on TikTok", source: "TikTok", date: "2026-06-15", classification: "relevant" as const, rq: "RQ1" },
  { id: 2, headline: "Audience members reveal top 5 convenience shortcuts", source: "Reddit", date: "2026-06-18", classification: "relevant" as const, rq: "RQ2" },
  { id: 3, headline: "Discussion thread on daily planning challenges", source: "Instagram", date: "2026-06-20", classification: "relevant" as const, rq: "RQ2" },
  { id: 4, headline: "Brand launches new product feature guide", source: "Facebook", date: "2026-07-01", classification: "relevant" as const, rq: "RQ1" },
  { id: 5, headline: "Consumer frustration with product quality — a rant", source: "Reddit", date: "2026-07-05", classification: "relevant" as const, rq: "RQ2" },
  { id: 6, headline: "Professional reviewer compares competing brands", source: "YouTube", date: "2026-06-22", classification: "partially_relevant" as const, rq: "RQ3" },
  { id: 7, headline: "New approach to common consumer pain point", source: "Instagram", date: "2026-07-10", classification: "relevant" as const, rq: "RQ3" },
  { id: 8, headline: "Industry expert shares preparation tips", source: "TikTok", date: "2026-07-12", classification: "partially_relevant" as const, rq: "RQ2" },
  { id: 9, headline: "Best coupon deals on related products this week", source: "Facebook", date: "2026-07-08", classification: "irrelevant" as const, rq: null },
  { id: 10, headline: "Emerging trend: consumers embrace new format", source: "TikTok", date: "2026-06-25", classification: "relevant" as const, rq: "RQ1" },
  { id: 11, headline: "Hiring: regional sales manager at competitor company", source: "LinkedIn", date: "2026-07-15", classification: "irrelevant" as const, rq: null },
  { id: 12, headline: "Consumer shows their organization system", source: "Instagram", date: "2026-07-02", classification: "relevant" as const, rq: "RQ2" },
];

const DEMO_FALSE_POSITIVES = [
  { pattern: "Professional / industry expert reviews", count: 12, suggestion: 'Add NOT ("expert review" OR "industry analysis")' },
  { pattern: "Off-topic adjacent content", count: 8, suggestion: 'Add NOT ("job posting" OR "hiring" OR "recruitment")' },
  { pattern: "Coupon / deal aggregator posts", count: 6, suggestion: "Exclusion already present — check engagement threshold" },
];

const DEMO_REFINEMENTS = [
  { id: "ref-1", label: "Add audience self-identification filter", description: 'Add audience-specific language terms to increase precision', impact: "+8% precision, -5% recall", query_addition: ' AND ("target audience term")' },
  { id: "ref-2", label: "Exclude professional content", description: 'Add NOT ("expert review" OR "industry report" OR "press release")', impact: "+4% precision", query_addition: ' AND NOT ("expert review" OR "industry report" OR "press release")' },
  { id: "ref-3", label: "Tighten engagement threshold", description: "Increase minimum engagements from 2 to 5", impact: "-15% volume, +6% precision", query_addition: "" },
];

interface Props {
  onNavigate: (page: string) => void;
}

export function QueryEvaluation({ onNavigate }: Props) {
  const { activeProject } = useProject();
  const demo = useDemoState();
  const [uploaded, setUploaded] = useState(false);
  const [simulating, setSimulating] = useState(false);
  type SampleRecord = { id: number; headline: string; source: string; date: string; classification: string; rq: string | null };
  const [records, setRecords] = useState<SampleRecord[]>(DEMO_SAMPLE_RECORDS);
  const [appliedRefinements, setAppliedRefinements] = useState<Set<string>>(new Set());

  const handleSimulateUpload = () => {
    setSimulating(true);
    setTimeout(() => {
      setSimulating(false);
      setUploaded(true);
      demo.setEvaluationRun(true);
      demo.addActivity("Sample Evaluated", "200-record Meltwater sample — 78% precision");
    }, 1200);
  };

  const handleCorrectClassification = (id: number, newClass: string) => {
    setRecords((prev) => prev.map((r) => r.id === id ? { ...r, classification: newClass } : r));
  };

  const handleApplyRefinement = (ref: typeof DEMO_REFINEMENTS[0]) => {
    if (appliedRefinements.has(ref.id)) return;
    setAppliedRefinements((prev) => new Set([...prev, ref.id]));
    if (ref.query_addition) {
      const newQuery = demo.balancedQuery + ref.query_addition;
      demo.updateBalancedQuery(newQuery, `Applied refinement: ${ref.label}`);
    }
    demo.addActivity("Refinement Applied", ref.label);
  };

  const relevant = records.filter((r) => r.classification === "relevant").length;
  const partial = records.filter((r) => r.classification === "partially_relevant").length;
  const irrelevant = records.filter((r) => r.classification === "irrelevant").length;
  const total = records.length;
  const precision = Math.round(((relevant + partial * 0.5) / total) * 100);
  const fpRate = Math.round((irrelevant / total) * 100);

  const rqCoverage: Record<string, number> = {};
  records.forEach((r) => { if (r.rq) rqCoverage[r.rq] = (rqCoverage[r.rq] || 0) + 1; });

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Query Evaluation Preview</h1>
          <p className="text-sm text-slate-500 mt-0.5">Meltwater sample analysis — {activeProject?.name ?? "Research Project"}</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 px-2.5 py-1 rounded-full">Demo Data</span>
          <span className="text-xs font-medium text-slate-500 bg-slate-100 border border-slate-200 px-2.5 py-1 rounded-full">
            Demo query — Meltwater validation pending
          </span>
        </div>
      </div>

      {!uploaded ? (
        <div className="bg-white border-2 border-dashed border-slate-200 rounded-xl p-10 text-center space-y-4">
          <div className="w-12 h-12 mx-auto bg-slate-100 rounded-xl flex items-center justify-center">
            <svg className="w-6 h-6 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><polyline points="10 9 9 9 8 9" /></svg>
          </div>
          <h3 className="text-sm font-semibold text-slate-700">Upload Meltwater Sample Dataset</h3>
          <p className="text-xs text-slate-500 max-w-md mx-auto">
            Export a 200-record sample from Meltwater using the approved balanced query, then upload the CSV or XLSX file here to evaluate query performance.
          </p>
          <button
            onClick={handleSimulateUpload}
            disabled={simulating}
            className="px-5 py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm disabled:opacity-50"
          >
            {simulating ? "Evaluating sample..." : "Simulate Upload"}
          </button>
          <p className="text-[10px] text-slate-400">Demo mode — generates synthetic sample records for evaluation</p>
        </div>
      ) : (
        <>
          <Card title="Evaluation Summary">
            <div className="grid grid-cols-6 gap-4 text-center mb-6">
              <div><div className="text-2xl font-bold text-slate-900 tabular-nums">{total}</div><div className="text-xs text-slate-400">Total</div></div>
              <div><div className="text-2xl font-bold text-emerald-600 tabular-nums">{relevant}</div><div className="text-xs text-slate-400">Relevant</div></div>
              <div><div className="text-2xl font-bold text-amber-600 tabular-nums">{partial}</div><div className="text-xs text-slate-400">Partial</div></div>
              <div><div className="text-2xl font-bold text-red-600 tabular-nums">{irrelevant}</div><div className="text-xs text-slate-400">Irrelevant</div></div>
              <div><div className="text-2xl font-bold text-slate-600 tabular-nums">3</div><div className="text-xs text-slate-400">Duplicates</div></div>
              <div><div className="text-2xl font-bold text-blue-600 tabular-nums">{total - 3}</div><div className="text-xs text-slate-400">Unique</div></div>
            </div>
            <div className="space-y-2">
              <ScoreBar label="Precision Estimate" value={precision} />
              <ScoreBar label="False-Positive Rate" value={fpRate} invert />
            </div>
          </Card>

          <Card title="Research-Question Coverage">
            <div className="grid grid-cols-4 gap-3">
              {["RQ1", "RQ2", "RQ3", "RQ4", "RQ5", "RQ6", "RQ7", "RQ8"].map((rq) => (
                <div key={rq} className="flex items-center justify-between bg-slate-50 rounded-lg px-3 py-2">
                  <span className="text-xs font-semibold text-slate-600">{rq}</span>
                  <span className={`text-xs font-bold tabular-nums ${(rqCoverage[rq] || 0) > 0 ? "text-emerald-600" : "text-red-500"}`}>
                    {rqCoverage[rq] || 0} hits
                  </span>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Common False Positives">
            <div className="space-y-3">
              {DEMO_FALSE_POSITIVES.map((fp, i) => (
                <div key={i} className="flex items-start justify-between gap-4 py-2 border-b border-slate-50 last:border-0">
                  <div className="flex-1">
                    <div className="text-sm text-slate-700">{fp.pattern}</div>
                    <div className="text-xs text-slate-400 mt-0.5">{fp.count} occurrences in sample</div>
                  </div>
                  <code className="text-[10px] text-blue-600 bg-blue-50 px-2 py-1 rounded font-mono max-w-xs truncate">{fp.suggestion}</code>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Query Refinement Recommendations">
            <div className="space-y-3">
              {DEMO_REFINEMENTS.map((ref) => {
                const applied = appliedRefinements.has(ref.id);
                return (
                  <div key={ref.id} className={`flex items-start justify-between gap-4 p-3 rounded-lg border ${applied ? "border-emerald-200 bg-emerald-50/50" : "border-slate-100 bg-white"}`}>
                    <div className="flex-1">
                      <div className="text-sm font-medium text-slate-700">{ref.label}</div>
                      <div className="text-xs text-slate-500 mt-0.5">{ref.description}</div>
                      <div className="text-[10px] text-slate-400 mt-1">Expected impact: {ref.impact}</div>
                    </div>
                    <button
                      onClick={() => handleApplyRefinement(ref)}
                      disabled={applied}
                      className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors shrink-0 ${
                        applied ? "bg-emerald-100 text-emerald-700" : "bg-blue-600 text-white hover:bg-blue-700"
                      }`}
                    >
                      {applied ? "Applied" : "Apply"}
                    </button>
                  </div>
                );
              })}
            </div>
          </Card>

          <Card title="Sample Records">
            <div className="space-y-1">
              <div className="grid grid-cols-[1fr_80px_80px_100px_80px] gap-3 text-[10px] font-semibold text-slate-400 uppercase tracking-wide pb-2 border-b border-slate-100">
                <span>Headline</span>
                <span>Source</span>
                <span>Date</span>
                <span>Classification</span>
                <span>RQ</span>
              </div>
              {records.map((r) => (
                <div key={r.id} className="grid grid-cols-[1fr_80px_80px_100px_80px] gap-3 py-2 items-center text-sm border-b border-slate-50 last:border-0">
                  <span className="text-slate-700 text-xs truncate">{r.headline}</span>
                  <span className="text-xs text-slate-400">{r.source}</span>
                  <span className="text-xs text-slate-400 tabular-nums">{r.date.slice(5)}</span>
                  <select
                    value={r.classification}
                    onChange={(e) => handleCorrectClassification(r.id, e.target.value as "relevant" | "partially_relevant" | "irrelevant")}
                    className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border-0 cursor-pointer ${
                      r.classification === "relevant" ? "text-emerald-700 bg-emerald-50" :
                      r.classification === "partially_relevant" ? "text-amber-700 bg-amber-50" :
                      "text-red-600 bg-red-50"
                    }`}
                  >
                    <option value="relevant">Relevant</option>
                    <option value="partially_relevant">Partial</option>
                    <option value="irrelevant">Irrelevant</option>
                  </select>
                  <span className="text-xs text-slate-400 font-mono">{r.rq || "—"}</span>
                </div>
              ))}
            </div>
          </Card>

          <div className="flex items-center justify-between">
            <button
              onClick={() => onNavigate("search-strategy")}
              className="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
            >
              Back to Search Strategy
            </button>
            <button
              onClick={() => onNavigate("data-sources")}
              className="px-5 py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm"
            >
              Proceed to Data Sources
            </button>
          </div>
        </>
      )}
    </div>
  );
}
