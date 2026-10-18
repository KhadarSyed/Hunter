import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

const STAGES = ["gate", "ingest", "routing", "plan", "classify", "compute", "insights", "template", "render", "qc",
  "index", "design", "assets", "compose", "export", "repair"] as const;
type Stage = (typeof STAGES)[number];
const LABELS: Record<string, string> = { gate: "Gate", ingest: "Ingest", routing: "Routing", plan: "Plan",
  classify: "Classify", compute: "Compute", insights: "Insights", template: "Template", render: "Render", qc: "QC",
  index: "References", design: "Design", assets: "Photos", compose: "Compose", export: "Export", repair: "Repair" };

/** What each stage of backend/domains/deliverable/engine.py does, shown when its tag is hovered or focused. `share` is the
 * engine's STAGE_WEIGHTS (percent of a typical run, measured on run 45); keep both in step with the engine. */
const GUIDE: Record<Stage, { title: string; purpose: string; processes: string[]; why: string; share: number }> = {
  gate: { title: "Checking approvals", share: 0,
    purpose: "Confirms the deck may be built before any work starts.",
    processes: ["The scope (Brief & Scope) is approved", "The search strategy is approved", "At least one dataset is approved"],
    why: "A deliverable is only ever built from inputs a person has signed off." },
  ingest: { title: "Ingesting approved datasets", share: 0,
    purpose: "Reads every approved dataset into one clean set of articles.",
    processes: ["Each approved Meltwater export", "The enrichment tags from the Review tab", "Duplicate URLs merged into one article"],
    why: "Every later number counts each article once." },
  routing: { title: "Routing articles to questions", share: 0.3,
    purpose: "Decides which research questions each article answers.",
    processes: ["The question it was uploaded for", "Every other question whose Meltwater query matches its text",
      "Syndicated copies grouped into one story", "The base N (unique articles across all questions)"],
    why: "A question with no upload of its own is answered by the articles that match its query." },
  plan: { title: "Planning analyses", share: 1.2,
    purpose: "Chooses the charts and tables that answer each question.",
    processes: ["The question's own dimensions (e.g. by sport, by brand)", "Asks written in the brief (e.g. social vs editorial)",
      "Articles that name the brand and can be cited"],
    why: "Each question gets the analysis it asks for, not only brand volume." },
  classify: { title: "Classifying entities", share: 0.2,
    purpose: "Pulls out the names the planned analyses need.",
    processes: ["Brands, products, experts or other entities per question", "Only the kinds a planned chart uses"],
    why: "Charts count real, named things rather than raw keywords." },
  compute: { title: "Computing charts and tables", share: 0,
    purpose: "Turns the routed articles into numbers.",
    processes: ["Overview: volume, media mix, timeline", "Client vs competitors: share of voice and sentiment",
      "Each question's planned analyses", "Off-topic names dropped from brand and product charts"],
    why: "Every figure on a slide comes from here, so it can be fact-checked later." },
  insights: { title: "Drafting cited insights", share: 7.6,
    purpose: "Writes the findings for each question.",
    processes: ["Insights per question, each tied to its source articles", "Summaries for each chart and theme",
      "The executive summary"],
    why: "Every claim carries citations a reader can open. Questions are drafted side by side." },
  template: { title: "Choosing a template", share: 0.1,
    purpose: "Picks the house PowerPoint template that fits the project's scope.",
    processes: ["The project's scope and research type", "The house template library"],
    why: "The classic deck follows the agreed house layout." },
  render: { title: "Building slides", share: 17.8,
    purpose: "Builds the classic deck.",
    processes: ["Slides with charts, tables and insights", "The citations appendix", "The page's charts and logos"],
    why: "This is the first complete deliverable; the brand-led presentation is added on top of it." },
  qc: { title: "Fact check and layout QC", share: 2.9,
    purpose: "Checks the classic deck before anyone sees it.",
    processes: ["Every number on a slide against the computed data", "Text that overflows its box (fixed where possible)",
      "Slide thumbnails", "The Word brief"],
    why: "Wrong figures or broken layouts are caught by the system, not by the client." },
  index: { title: "Reading reference decks", share: 7.7,
    purpose: "Learns layouts from the library of reference decks.",
    processes: ["Reference decks and their slide layouts", "Which layouts suit which kinds of content"],
    why: "The presentation follows proven designs instead of fixed presets." },
  design: { title: "Designing the deck", share: 0.6,
    purpose: "Chooses the presentation's look.",
    processes: ["A design family from the references", "A design system: brand colours and type"],
    why: "The deck looks like the brand, consistently from slide to slide." },
  assets: { title: "Finding photos & logos", share: 51.6,
    purpose: "Collects the images the slides need.",
    processes: ["Photos matching each slide's topic", "Screenshots of the cited articles", "Brand and competitor logos"],
    why: "Real images make the story concrete. This is the longest stage: many web searches and a headless browser." },
  compose: { title: "Composing slides", share: 1.5,
    purpose: "Lays out each slide of the presentation.",
    processes: ["The planned story, slide by slide", "Charts, insights, photos and logos placed in each layout"],
    why: "Content and design come together into finished slides." },
  export: { title: "Exporting PPTX & PDF", share: 4.5,
    purpose: "Produces the files you download.",
    processes: ["The presentation as PowerPoint", "The same deck as PDF"],
    why: "The deliverable is ready to share or edit." },
  repair: { title: "Repairing open deck checks", share: 4,
    purpose: "Runs only when a deck check or brief gap is still open, or when you press Fix.",
    processes: ["Each open deck check (e.g. an unverified logo)", "Each brief ask the deck does not yet answer",
      "A fresh export of the repaired deck"],
    why: "Open problems are fixed in place instead of rebuilding the whole deck." },
};

const STATUS_TEXT: Record<string, string> = { done: "Done", running: "Running now", failed: "Failed" };

type Anchor = { stage: Stage; left: number; top: number };

/** The run's stages as tags; hovering or focusing a tag opens a short guide to that stage. */
export function RunTimeline({ stages, details }: { stages: Record<string, string>; details: Record<string, string> }) {
  const [anchor, setAnchor] = useState<Anchor | null>(null);
  const hideTimer = useRef<number | undefined>(undefined);

  const show = (stage: Stage, el: HTMLElement) => {
    window.clearTimeout(hideTimer.current);
    const r = el.getBoundingClientRect();
    setAnchor({ stage, left: Math.min(Math.max(8, r.left), window.innerWidth - 336), top: r.bottom + 8 });
  };
  // a short delay lets the pointer move from the tag onto the pop-up without it closing
  const hide = () => { hideTimer.current = window.setTimeout(() => setAnchor(null), 120); };

  useEffect(() => {
    if (!anchor) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setAnchor(null); };
    const onScroll = () => setAnchor(null);
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onScroll, true);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("scroll", onScroll, true); };
  }, [anchor]);
  useEffect(() => () => window.clearTimeout(hideTimer.current), []);

  const guide = anchor ? GUIDE[anchor.stage] : null;
  const status = anchor ? stages[anchor.stage] : undefined;
  return (
    <>
      <ol className="flex flex-nowrap gap-1 overflow-x-auto" aria-label="Deliverable stages">
        {STAGES.map((s) => {
          const st = stages[s];
          const cls = st === "done" ? "bg-emerald-50 text-emerald-700 border-emerald-200"
            : st === "running" ? "bg-violet-50 text-violet-700 border-violet-200 animate-pulse"
            : st === "failed" ? "bg-red-50 text-red-700 border-red-200" : "bg-white text-slate-500 border-slate-200";
          return (
            <li key={s} tabIndex={0} aria-describedby={anchor?.stage === s ? "stage-guide" : undefined}
                onMouseEnter={(e) => show(s, e.currentTarget)} onMouseLeave={hide}
                onFocus={(e) => show(s, e.currentTarget)} onBlur={hide}
                className={`shrink-0 cursor-help whitespace-nowrap rounded-md border px-2 py-1 text-[11px] font-medium outline-none focus-visible:ring-2 focus-visible:ring-[#5B2C9D]/40 ${cls}`}>
              {LABELS[s]}
            </li>
          );
        })}
      </ol>
      {anchor && guide && createPortal(
        <div id="stage-guide" role="tooltip" onMouseEnter={() => window.clearTimeout(hideTimer.current)} onMouseLeave={hide}
          className="fixed z-[90] w-80 rounded-xl border border-slate-200 bg-white p-4 text-left shadow-xl"
          style={{ left: anchor.left, top: anchor.top }}>
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm font-semibold text-slate-900">{guide.title}</p>
            {status && (
              <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${status === "done"
                ? "bg-emerald-50 text-emerald-700" : status === "running" ? "bg-violet-50 text-violet-700" : "bg-red-50 text-red-700"}`}>
                {STATUS_TEXT[status] ?? status}
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-slate-600">{guide.purpose}</p>
          <p className="mt-3 text-[10px] font-semibold uppercase tracking-wide text-slate-400">What is processed</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-slate-700">
            {guide.processes.map((p) => <li key={p}>{p}</li>)}
          </ul>
          <p className="mt-3 text-[10px] font-semibold uppercase tracking-wide text-slate-400">Why</p>
          <p className="mt-1 text-xs text-slate-700">{guide.why}</p>
          {details[anchor.stage] && (
            <p className="mt-3 rounded-md bg-slate-50 px-2 py-1 text-[11px] text-slate-600">This run: {details[anchor.stage]}</p>
          )}
          <p className="mt-2 text-[10px] text-slate-400">
            {guide.share >= 1 ? `About ${Math.round(guide.share)}% of a typical run's time` : "Takes seconds"}
          </p>
        </div>,
        document.body,
      )}
    </>
  );
}
