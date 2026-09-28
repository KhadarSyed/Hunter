export interface RunSummary {
  id: number;
  brief_filename: string;
  client_guess: string | null;
  started_at: number;
  finished_at: number | null;
  status: "running" | "completed" | "failed";
  output_path: string | null;
}

export interface RunEvent {
  ts: number;
  event_type: string;
  payload: Record<string, any>;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  ts: number;
}

export interface Settings {
  repo_dir: string;
  briefs_dir: string;
  output_dir: string;
  ignore_patterns: string[];
  ollama_host: string;
  embed_model: string;
  chat_model: string;
  top_k_candidates: number;
  relevance_threshold: number;
}

export interface StatusInfo {
  ollama_reachable: boolean;
  slide_count: number;
  deck_count: number;
  run_busy: boolean;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export const api = {
  listRuns: () => fetch("/api/runs").then((r) => json<RunSummary[]>(r)),
  getRun: (id: number) =>
    fetch(`/api/runs/${id}`).then((r) => json<{ run: RunSummary; events: RunEvent[]; chat: ChatMessage[] }>(r)),
  downloadUrl: (id: number) => `/api/runs/${id}/download`,
  getSettings: () => fetch("/api/settings").then((r) => json<Settings>(r)),
  saveSettings: (s: Settings) =>
    fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(s),
    }).then((r) => json<{ ok: boolean }>(r)),
  getStatus: () => fetch("/api/status").then((r) => json<StatusInfo>(r)),
  triggerRun: (payload: { text?: string; filename?: string }) =>
    fetch("/api/runs/trigger", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then((r) => json<{ ok: boolean; brief_filename?: string; error?: string }>(r)),
  postChat: (content: string, run_id: number | null) =>
    fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, run_id }),
    }).then((r) => json<{ ok: boolean }>(r)),
  getChat: (run_id: number | null) =>
    fetch(`/api/chat${run_id ? `?run_id=${run_id}` : ""}`).then((r) => json<ChatMessage[]>(r)),
  deleteRun: (id: number) =>
    fetch(`/api/runs/${id}`, { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),
  resetRunLock: () =>
    fetch("/api/runs/reset-lock", { method: "POST" }).then((r) => json<{ ok: boolean; was_busy: boolean }>(r)),
  clearChat: () =>
    fetch("/api/chat", { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),
  triggerTemplate: (text: string, includeResearch: boolean = false) =>
    fetch("/api/runs/template", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, include_research: includeResearch }),
    }).then((r) => json<{ ok: boolean; brief_filename?: string; error?: string }>(r)),
};
