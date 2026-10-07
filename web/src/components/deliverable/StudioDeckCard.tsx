import { Icon } from "@iconify/react";
import { intelApi } from "../../services/intel-api";
import type { DeliverableSection } from "../../services/intel-api";

const STATUS_STYLE: Record<string, string> = {
  covered: "bg-emerald-50 text-emerald-700 border-emerald-200",
  partial: "bg-amber-50 text-amber-700 border-amber-200",
  missing: "bg-red-50 text-red-700 border-red-200",
};

/** The brand-led presentation: live preview, why this design, how well it answers the brief, downloads. */
export function StudioDeckCard({ projectId, runId, studio }: { projectId: number; runId: number; studio: DeliverableSection }) {
  const deckUrl = intelApi.deliverableDeckUrl(projectId, runId, "deck.html");
  const score = studio.scorecard ?? { covered: 0, partial: 0, missing: 0 };
  const gaps = (studio.checklist ?? []).filter((r) => r.status !== "covered");
  return (
    <section className="space-y-4 rounded-2xl border border-violet-100 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold text-slate-900">
            <Icon icon="lucide:presentation" width={18} className="text-[#5B2C9D]" /> Presentation
          </h2>
          {studio.family && (
            <p className="mt-1 text-xs text-slate-500">Design: {studio.family.replace("_", " ")} — {studio.family_reason}</p>
          )}
          {studio.design_system && (
            <p className="mt-1 text-xs text-slate-500">Design system: {studio.design_system} — {studio.design_reason}</p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <a href={intelApi.deliverableDownloadUrl(projectId, runId, "studio_pptx")}
            className="inline-flex items-center gap-2 rounded-lg bg-[#5B2C9D] px-4 py-2 text-sm font-medium text-white">
            <Icon icon="lucide:download" width={16} /> Download .pptx</a>
          <a href={intelApi.deliverableDownloadUrl(projectId, runId, "pdf")}
            className="inline-flex items-center gap-2 rounded-lg border border-[#5B2C9D] px-4 py-2 text-sm font-medium text-[#5B2C9D]">
            <Icon icon="lucide:file-down" width={16} /> Download .pdf</a>
          <a href={deckUrl} target="_blank" rel="noopener noreferrer"
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700">
            <Icon icon="lucide:external-link" width={16} /> Open HTML deck</a>
        </div>
      </div>
      <iframe title="Presentation preview" src={deckUrl} sandbox="allow-scripts" className="aspect-video w-full rounded-xl border border-slate-200 bg-black" />
      <div>
        <p className="mb-2 text-sm font-semibold text-slate-800">Did we answer the brief?</p>
        <div className="flex flex-wrap gap-2">
          {(["covered", "partial", "missing"] as const).map((k) => (
            <span key={k} className={`rounded-full border px-3 py-1 text-xs font-semibold ${STATUS_STYLE[k]}`}>
              {score[k]} {k}
            </span>
          ))}
        </div>
        {gaps.length > 0 && (
          <ul className="mt-3 space-y-1 text-xs text-slate-600">
            {gaps.map((g) => (
              <li key={g.ask}><span className="font-semibold capitalize">{g.status}:</span> {g.ask} — {g.note}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
