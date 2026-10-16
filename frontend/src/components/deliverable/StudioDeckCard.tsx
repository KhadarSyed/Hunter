import { useState } from "react";
import { Icon } from "@iconify/react";
import { intelApi } from "../../services/intel-api";
import type { DeliverableSection, RepairScope } from "../../services/intel-api";

const STATUS_STYLE: Record<string, string> = {
  covered: "bg-emerald-50 text-emerald-700 border-emerald-200",
  partial: "bg-amber-50 text-amber-700 border-amber-200",
  missing: "bg-red-50 text-red-700 border-red-200",
};
const CHECK_STYLE: Record<string, string> = {
  pass: "bg-emerald-50 text-emerald-700 border-emerald-200",
  warn: "bg-amber-50 text-amber-700 border-amber-200",
  fail: "bg-red-50 text-red-700 border-red-200",
};

type FixButtonProps = { label: string; isRepairing: boolean; onClick: () => void };

/** Sends the repair agent at exactly the open items of its panel; its progress streams into the run log above. */
function FixButton({ label, isRepairing, onClick }: FixButtonProps) {
  return (
    <button type="button" onClick={onClick} disabled={isRepairing}
      className="inline-flex items-center gap-1.5 rounded-lg bg-[#5B2C9D] px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition hover:bg-[#4a2380] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5B2C9D] disabled:cursor-wait disabled:opacity-60">
      <Icon icon={isRepairing ? "lucide:loader-circle" : "lucide:wrench"} width={14} className={isRepairing ? "animate-spin" : ""} />
      {isRepairing ? "Repairing..." : label}
    </button>
  );
}

/** In place of a Fix button on runs made before repairs were saved with the deck: those need one regenerate first. */
function RegenerateHint() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800"
      title="Quick fixes need the repair notes saved with newer decks. Regenerate this deliverable once and Fix will work on it.">
      <Icon icon="lucide:info" width={14} /> Regenerate once to enable Fix
    </span>
  );
}

/** The deck in an iframe, with a loading state until it has loaded (a 100-slide deck takes a few seconds). */
function DeckPreview({ src }: { src: string }) {
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);
  const isLoading = loadedSrc !== src;
  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-xl border border-slate-200 bg-slate-50 lg:col-span-2 lg:self-start">
      {isLoading && (
        <div role="status" className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-slate-500">
          <Icon icon="lucide:loader-circle" width={32} className="animate-spin text-[#5B2C9D]" />
          <span className="text-sm font-medium">Loading the presentation...</span>
        </div>
      )}
      <iframe title="Presentation preview" src={src} sandbox="allow-scripts" onLoad={() => setLoadedSrc(src)}
        className={`h-full w-full bg-black transition-opacity duration-300 ${isLoading ? "opacity-0" : "opacity-100"}`} />
    </div>
  );
}

type Props = {
  projectId: number;
  runId: number;
  studio: DeliverableSection;
  isRepairing: boolean;
  /** False on runs made before repairs were saved with the deck: Fix would be refused, so a hint shows instead. */
  canRepair: boolean;
  onRepair: (scope: RepairScope) => void;
};

/** The brand-led presentation: live preview, why this design, how well it answers the brief, downloads. */
export function StudioDeckCard({ projectId, runId, studio, isRepairing, canRepair, onRepair }: Props) {
  const deckUrl = intelApi.deliverableDeckUrl(projectId, runId, "deck.html");
  const score = studio.scorecard ?? { covered: 0, partial: 0, missing: 0 };
  const gaps = (studio.checklist ?? []).filter((r) => r.status !== "covered");
  const checks = studio.validation ?? [];
  const openChecks = checks.filter((c) => c.status !== "pass");
  const notes = checks.filter((c) => c.status === "pass" && c.detail);
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
      <div className="grid gap-5 lg:grid-cols-3">
        <DeckPreview src={deckUrl} />
        <div className="space-y-5 lg:max-h-[34rem] lg:overflow-y-auto lg:pr-1">
          <div>
            <div className="mb-2 flex items-center justify-between gap-3">
              <p className="text-sm font-semibold text-slate-800">Did we answer the brief?</p>
              {gaps.length > 0 && (canRepair ? (
                <FixButton label={`Fix ${gaps.length} brief gap${gaps.length > 1 ? "s" : ""}`} isRepairing={isRepairing}
                  onClick={() => onRepair("brief")} />
              ) : <RegenerateHint />)}
            </div>
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
          {checks.length > 0 && (
            <div>
              <div className="mb-2 flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-slate-800">Deck checks</p>
                {openChecks.length > 0 && (canRepair ? (
                  <FixButton label={`Fix ${openChecks.length} open check${openChecks.length > 1 ? "s" : ""}`}
                    isRepairing={isRepairing} onClick={() => onRepair("checks")} />
                ) : <RegenerateHint />)}
              </div>
              <div className="flex flex-wrap gap-2">
                {(["pass", "warn", "fail"] as const).map((k) => (
                  <span key={k} className={`rounded-full border px-3 py-1 text-xs font-semibold ${CHECK_STYLE[k]}`}>
                    {checks.filter((c) => c.status === k).length} {k === "pass" ? "passed" : k === "warn" ? "warnings" : "failed"}
                  </span>
                ))}
              </div>
              {openChecks.length > 0 && (
                <ul className="mt-3 space-y-1 text-xs text-slate-600">
                  {openChecks.map((c) => (
                    <li key={c.check}>
                      <span className={`mr-1 font-semibold ${c.status === "fail" ? "text-red-700" : "text-amber-700"}`}>
                        {c.status === "fail" ? "Failed" : "Warning"}:
                      </span>
                      {c.check} — {c.detail}
                    </li>
                  ))}
                </ul>
              )}
              {notes.length > 0 && (
                <ul className="mt-2 space-y-1 text-xs text-slate-500">
                  {notes.map((c) => (
                    <li key={c.check}><span className="mr-1 font-semibold text-emerald-700">Passed, note:</span>{c.check} — {c.detail}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
