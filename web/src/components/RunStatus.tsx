import React, { useMemo } from "react";
import { RunEvent, RunSummary, api } from "../lib/api";
import { DownloadIcon } from "./icons";

export function RunStatus({ run, events }: { run: RunSummary | null; events: RunEvent[] }) {
  const manifest = useMemo(() => {
    const items: { kind: "reused" | "drafted"; title: string; detail: string }[] = [];
    for (const ev of events) {
      if (ev.event_type === "slide_selected") {
        items.push({
          kind: "reused",
          title: ev.payload.title,
          detail: `${ev.payload.source_client} · slide ${ev.payload.slide_no}`,
        });
      } else if (ev.event_type === "drafted_slide") {
        items.push({ kind: "drafted", title: ev.payload.title, detail: ev.payload.section });
      }
    }
    return items;
  }, [events]);

  const candidateCount = events.find((e) => e.event_type === "slides_retrieved")?.payload?.count;
  const sectionTitles: string[] = events.find((e) => e.event_type === "reasoning_complete")?.payload?.section_titles || [];

  if (!run) {
    return (
      <div className="status-panel">
        <div className="status-panel-title">Run status</div>
        <div className="empty-state-sub">No run selected yet. Drop a brief in the inbox folder, or start one from the composer.</div>
      </div>
    );
  }

  return (
    <div className="status-panel">
      <div className="status-panel-title">{run.client_guess || run.brief_filename}</div>
      <div>
        <div className="stat-row">
          <span>Status</span>
          <span>{run.status}</span>
        </div>
        {candidateCount !== undefined && (
          <div className="stat-row">
            <span>Candidates evaluated</span>
            <span>{candidateCount}</span>
          </div>
        )}
        {sectionTitles.length > 0 && (
          <div className="stat-row">
            <span>Sections</span>
            <span>{sectionTitles.length}</span>
          </div>
        )}
        <div className="stat-row">
          <span>Slides reused</span>
          <span>{manifest.filter((m) => m.kind === "reused").length}</span>
        </div>
        <div className="stat-row">
          <span>Slides drafted</span>
          <span>{manifest.filter((m) => m.kind === "drafted").length}</span>
        </div>
      </div>

      {manifest.length > 0 && (
        <div>
          <div className="sidebar-section-label">Slide manifest</div>
          {manifest.map((m, i) => (
            <div className="manifest-item" key={i}>
              <span className={`manifest-badge ${m.kind}`}>{m.kind === "reused" ? "reused" : "new"}</span>
              <span className="manifest-item-text" title={`${m.title} — ${m.detail}`}>
                {m.title}
              </span>
            </div>
          ))}
        </div>
      )}

      {run.status === "completed" && run.output_path && (
        <a className="btn-primary download-btn" href={api.downloadUrl(run.id)} download>
          <DownloadIcon size={14} />
          Download deck
        </a>
      )}
    </div>
  );
}
