import { useEffect, useState } from "react";
import { agentSocket } from "../services/ws";

const CHECK_MS = 5 * 60 * 1000; // fallback; a deploy is usually caught when the live socket reconnects

/** True once the server serves a newer build than this tab runs (vite.config.ts writes the same id into
 *  /version.json). Checked on socket reconnect (a deploy restarts the server), on tab focus and every 5 minutes. */
function useNewVersion(): boolean {
  const [stale, setStale] = useState(false);
  useEffect(() => {
    if (import.meta.env.DEV) return;
    let active = true;
    const check = async () => {
      try {
        const r = await fetch("/version.json", { cache: "no-store" });
        if (!r.ok) return;
        const v = (await r.json()) as { build?: string };
        if (active && v.build && v.build !== __BUILD_ID__) setStale(true);
      } catch { /* offline or restarting: the next trigger checks again */ }
    };
    const onVisible = () => { if (document.visibilityState === "visible") void check(); };
    const offSocket = agentSocket.onStatus((connected) => { if (connected) void check(); });
    document.addEventListener("visibilitychange", onVisible);
    const timer = window.setInterval(check, CHECK_MS);
    void check();
    return () => {
      active = false;
      offSocket();
      document.removeEventListener("visibilitychange", onVisible);
      window.clearInterval(timer);
    };
  }, []);
  return stale;
}

/** "A new version is available": Reload keeps the session (server-side, HttpOnly cookie); Later hides it. */
export function NewVersionBanner() {
  const stale = useNewVersion();
  const [dismissed, setDismissed] = useState(false);
  if (!stale || dismissed) return null;
  return (
    <div role="status" aria-live="polite"
         className="fixed bottom-5 left-1/2 z-[100] flex w-[min(36rem,calc(100vw-2rem))] -translate-x-1/2 items-center gap-4 rounded-2xl border border-violet-200 bg-white px-5 py-3 shadow-2xl shadow-violet-900/15">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-violet-50 text-[#5B2C9D]" aria-hidden="true">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12a9 9 0 1 1-3-6.7L21 8" /><path d="M21 3v5h-5" /></svg>
      </span>
      <div className="min-w-0 flex-1 text-sm">
        <p className="font-semibold text-slate-900">A new version of AlphaMetricx is available</p>
        <p className="text-slate-500">Reload to use it. You stay signed in.</p>
      </div>
      <button type="button" onClick={() => setDismissed(true)}
              className="shrink-0 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100">Later</button>
      <button type="button" onClick={() => window.location.reload()}
              className="shrink-0 rounded-lg bg-[#5B2C9D] px-4 py-2 text-sm font-semibold text-white hover:bg-[#4a2380]">Reload</button>
    </div>
  );
}
