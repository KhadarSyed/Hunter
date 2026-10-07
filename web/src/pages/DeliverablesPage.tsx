import { useEffect, useState } from "react";
import { intelApi } from "../services/intel-api";
import type { DeliverableCard, DeliverablePayload, DeliverableSection } from "../services/intel-api";
import { agentSocket } from "../services/ws";
import { useActiveProjectId } from "../context/project-context";
import { ChartRenderer } from "../components/deliverable/ChartRenderer";
import { RunTimeline } from "../components/deliverable/RunTimeline";

const MAX_TABLE_ROWS = 12;

function CiteChip({ n }: { n: number }) {
  return <span className="ml-0.5 rounded bg-violet-50 px-1 text-[10px] font-medium text-violet-700">{n}</span>;
}

function Cards({ cards }: { cards: DeliverableCard[] }) {
  if (!cards.length) return null;
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {cards.map((c, i) => (
        <div key={i} className="rounded-xl border border-violet-100 bg-violet-50/30 p-4">
          <p className="text-sm font-semibold text-violet-800">{c.headline}</p>
          <p className="mt-1 text-xs text-slate-600">
            {c.text}
            {c.citations.map((n) => <CiteChip key={n} n={n} />)}
          </p>
        </div>
      ))}
    </div>
  );
}

function SectionView({ section }: { section: DeliverableSection }) {
  if (section.skipped) {
    return <p className="text-xs text-slate-400">{section.title}: {section.skipped}</p>;
  }
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <p className="mb-2 text-sm font-semibold text-slate-800">{section.title}</p>
      {section.chart && <ChartRenderer spec={section.chart} height={260} />}
      {section.table && (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="bg-violet-50 text-violet-800">
                {section.table.header.map((h) => <th key={h} className="px-2 py-1.5 font-semibold">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {section.table.rows.slice(0, MAX_TABLE_ROWS).map((row, i) => (
                <tr key={i} className="border-t border-slate-100">
                  {row.map((v, j) => <td key={j} className="px-2 py-1.5 text-slate-600">{v}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {section.notes?.filter((n) => n !== "logos").map((n) => (
        <p key={n} className="mt-1 text-[11px] text-slate-400">{n}</p>
      ))}
    </div>
  );
}

export function DeliverablesPage({ onNavigate }: { onNavigate: (page: string) => void }) {
  const projectId = useActiveProjectId() ?? 1;
  const [payload, setPayload] = useState<DeliverablePayload>({ run: null, sections: [] });
  const [details, setDetails] = useState<Record<string, string>>({});
  const [startError, setStartError] = useState<string | null>(null);

  useEffect(() => {
    agentSocket.connect();
    intelApi.deliverableLatest(projectId).then(setPayload).catch(() => undefined);
    const off = agentSocket.onMessage((msg) => {
      if (msg.project_id !== projectId) return;
      if (msg.type === "deliverable_stage") {
        setPayload((p) => (p.run && p.run.id === msg.run_id
          ? { ...p, run: { ...p.run, stage: msg.stage, stages: { ...p.run.stages, [msg.stage]: msg.status } } } : p));
        if (msg.detail) setDetails((d) => ({ ...d, [msg.stage]: msg.detail }));
      } else if (msg.type === "deliverable_section") {
        setPayload((p) => (p.run && p.run.id === msg.run_id
          ? { ...p, sections: [...p.sections.filter((s) => s.id !== msg.section.id), msg.section] } : p));
      } else if (msg.type === "deliverable_completed" || msg.type === "deliverable_failed") {
        intelApi.deliverableLatest(projectId).then(setPayload).catch(() => undefined);
      }
    });
    return () => { off(); };
  }, [projectId]);

  const generate = async () => {
    setStartError(null);
    setDetails({});
    try {
      const { run_id } = await intelApi.deliverableRun(projectId);
      setPayload({ run: { id: run_id, project_id: projectId, status: "running", stage: "gate", stages: {},
        pptx_path: null, docx_path: null, error: null }, sections: [] });
    } catch (e) {
      setStartError(e instanceof Error ? e.message : "Could not start the deliverable run");
    }
  };

  const run = payload.run;
  const byId = (id: string) => payload.sections.find((s) => s.id === id);
  const rqIds = [...new Set(payload.sections.map((s) => s.rq_id).filter(Boolean))] as string[];
  const collection = byId("data-collection")?.data;
  const summary = byId("executive-summary");
  const overview = byId("overview");
  const qc = byId("qc")?.report;
  const running = run?.status === "running";

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-8 py-10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Deliverables</h1>
          <p className="mt-1 text-sm text-slate-500">Charts, tables, cited insights and a brand-styled deck, built from your approved data</p>
        </div>
        <button onClick={generate} disabled={running}
          className="rounded-lg bg-[#5B2C9D] px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
          {running ? "Generating..." : run ? "Regenerate" : "Generate Deliverable"}
        </button>
      </div>

      {(startError || (run?.status === "failed" && run.error)) && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{startError || run?.error}</div>
      )}

      {run && <RunTimeline stages={run.stages ?? {}} details={details} />}

      {collection && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[["Files", collection.files], ["Unique URLs", collection.unique_urls], ["Stories", collection.stories], ["Base N", collection.base_n]].map(([label, value]) => (
            <div key={label} className="rounded-xl border border-slate-200 bg-white p-4 text-center">
              <p className="text-2xl font-bold text-[#5B2C9D]">{value}</p>
              <p className="text-xs text-slate-500">{label}</p>
            </div>
          ))}
        </div>
      )}

      {summary?.answers && (
        <div className="grid gap-3 md:grid-cols-3">
          {summary.answers.map((a) => (
            <div key={a.rq_id} className="rounded-xl border border-violet-100 bg-white p-4">
              <p className="text-3xl font-bold text-[#5B2C9D]">{a.value}</p>
              <p className="text-xs font-semibold text-slate-700">{a.rq_id}</p>
              <p className="mt-1 text-xs text-slate-500">{a.answer}</p>
            </div>
          ))}
        </div>
      )}

      {overview?.chart && <SectionView section={overview} />}

      {rqIds.map((rq) => {
        const sections = payload.sections.filter((s) => s.rq_id === rq && s.module !== "insights");
        const insights = byId(`${rq.toLowerCase()}-insights`)?.insights ?? [];
        return (
          <section key={rq} className="space-y-3 rounded-2xl border border-slate-200 bg-slate-50/40 p-5">
            <h2 className="text-base font-semibold text-slate-900">{rq}</h2>
            <div className="grid gap-3 md:grid-cols-2">
              {sections.map((s) => <SectionView key={s.id} section={s} />)}
            </div>
            <Cards cards={insights} />
          </section>
        );
      })}

      {summary?.takeaways && summary.takeaways.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-base font-semibold text-slate-900">Key takeaways</h2>
          <Cards cards={summary.takeaways} />
        </section>
      )}

      {qc && (
        <div className={`rounded-xl border p-4 text-sm ${qc.ready ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"}`}>
          {qc.ready ? "Ready" : `${qc.facts.length} fact issues · ${qc.layout.length} layout issues`}
          <span className="ml-2 text-xs opacity-80">{qc.fixed} auto-fixed</span>
        </div>
      )}

      {run && qc && qc.pngs.length > 0 && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {qc.pngs.map((_, i) => (
            <img key={i} loading="lazy" alt={`Slide ${i + 1}`} className="rounded-lg border border-slate-200"
              src={intelApi.deliverableThumbUrl(projectId, run.id, i + 1)} />
          ))}
        </div>
      )}

      {run?.status === "completed" && (
        <div className="flex gap-3">
          <a href={intelApi.deliverableDownloadUrl(projectId, run.id, "pptx")}
            className="rounded-lg bg-[#5B2C9D] px-4 py-2 text-sm font-medium text-white">Download .pptx</a>
          <a href={intelApi.deliverableDownloadUrl(projectId, run.id, "docx")}
            className="rounded-lg border border-[#5B2C9D] px-4 py-2 text-sm font-medium text-[#5B2C9D]">Download .docx</a>
        </div>
      )}

      <div>
        <button onClick={() => onNavigate("analysis")} className="text-sm font-medium text-slate-500 hover:text-slate-700">
          Back to Analysis
        </button>
      </div>
    </div>
  );
}
