import React from "react";
import { RunEvent } from "../lib/api";
import { iconForEvent, CheckIcon, AlertIcon } from "./icons";

function describeEvent(ev: RunEvent): { label: string; detail?: string } {
  const p = ev.payload;
  switch (ev.event_type) {
    case "run_started":
      return { label: "Received new brief", detail: p.brief_filename };
    case "brief_parsing":
      return { label: "Reading brief", detail: p.filename };
    case "brief_parsed":
      return { label: "Brief parsed", detail: `${p.char_count} characters` };
    case "indexing_check":
      return { label: "Checking repository index for changes" };
    case "index_indexing_deck":
      return { label: "Indexing deck", detail: p.deck };
    case "index_indexed_deck":
      return { label: "Indexed deck", detail: `${p.deck} — ${p.slides} slides` };
    case "index_index_error":
      return { label: "Could not index a deck", detail: `${p.deck}: ${p.error}` };
    case "indexing_done":
      return {
        label: "Repository index up to date",
        detail: `${p.total_slides} slides across ${p.total_decks} decks (${p.reindexed} refreshed, ${p.skipped_unchanged} unchanged)`,
      };
    case "embedding_brief":
      return { label: "Embedding brief for semantic search" };
    case "retrieving_slides":
      return { label: "Searching repository for relevant slides" };
    case "slides_retrieved":
      return { label: `Found ${p.count} candidate slides`, detail: (p.top_titles || []).slice(0, 3).join(" · ") };
    case "reasoning_start":
      return { label: "Evaluating candidates & planning deck structure", detail: `${p.candidate_count} candidates under review` };
    case "reasoning_complete":
      return { label: "Deck structure planned", detail: (p.section_titles || []).join(" · ") };
    case "slide_selected":
      return { label: `Reusing slide from ${p.source_client}`, detail: `${p.title} (${p.deck} · slide ${p.slide_no}) → "${p.section}"` };
    case "drafting_slide":
      return { label: `Drafting new slide for "${p.section}"`, detail: p.gap };
    case "drafted_slide":
      return { label: "Drafted slide ready", detail: p.title };
    case "draft_failed":
      return { label: "A slide draft failed", detail: p.error };
    case "assembling_deck":
      return { label: "Assembling final deck", detail: p.output_name };
    case "deck_saved":
      return { label: "Deck saved", detail: p.output_path };
    case "research_started":
      return { label: "Starting secondary research", detail: p.client };
    case "research_research_searching":
    case "research_searching":
      return { label: `Searching web (${p.index}/${p.total})`, detail: p.query };
    case "research_research_results":
    case "research_results":
      return { label: `Found ${p.total_sources} sources from web search` };
    case "research_research_writing":
    case "research_writing":
      return { label: "Writing research report (Word document)" };
    case "research_research_complete":
    case "research_complete":
      return { label: "Research report complete", detail: `${p.source_count} sources cited` };
    case "research_saved":
      return { label: "Research report saved", detail: p.output_path };
    case "run_complete":
      return { label: "Run complete", detail: p.research_path ? "Presentation + Research report saved" : undefined };
    case "run_failed":
      return { label: "Run failed", detail: p.error };
    default:
      return { label: ev.event_type };
  }
}

export function LiveFeed({ events, isActive, title }: { events: RunEvent[]; isActive: boolean; title: string }) {
  if (events.length === 0) return null;
  return (
    <div className="feed-card">
      <div className="feed-card-header">
        {isActive ? <span className="spinner" /> : <CheckIcon size={14} />}
        <span className="feed-card-title">{title}</span>
      </div>
      <div className="feed-steps">
        {events.map((ev, i) => {
          const { label, detail } = describeEvent(ev);
          const isLast = i === events.length - 1;
          const isError = ev.event_type.includes("fail") || ev.event_type.includes("error");
          return (
            <div className="feed-step" key={i}>
              <span className={`feed-step-icon ${isError ? "error" : isLast && isActive ? "" : "done"}`}>
                {isError ? <AlertIcon size={11} /> : isLast && isActive ? <span className="spinner" /> : iconForEvent(ev.event_type, 11)}
              </span>
              <div className="feed-step-body">
                <div className="feed-step-label">{label}</div>
                {detail && <div className="feed-step-detail">{detail}</div>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
