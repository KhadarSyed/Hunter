import { useEffect, useState } from "react";
import { useAuth } from "../context/auth-context";
import { intelApi, type DataSourceRecord } from "../services/intel-api";
import { BrandLogo } from "./BrandLogo";
import { formatRelativeOrDate } from "../utils/time";

const POLL_MS = 60_000;

/** Bell icon badged with the count of expired org data-source keys (Tavily/SerpAPI).
 * Admin/Super Admin only — Analysers don't manage org credentials. Renew opens the
 * vendor's own key-management page; the item disappears once the Admin enters a working
 * key (status flips back to "ok" reactively, the next time the key is used for real, or
 * immediately after "Validate now" in Settings > Data Sources). */
export function NotificationBell() {
  const { user } = useAuth();
  const canManage = user?.role === "admin" || user?.role === "super_admin";
  const [open, setOpen] = useState(false);
  const [sources, setSources] = useState<DataSourceRecord[] | null>(null);

  useEffect(() => {
    if (!canManage) return;
    let cancelled = false;
    const load = () => {
      intelApi.listDataSources().then((list) => { if (!cancelled) setSources(list); }).catch(() => {});
    };
    load();
    const id = setInterval(load, POLL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, [canManage]);

  if (!canManage) return null;

  const expired = (sources ?? []).filter((s) => s.status === "expired");

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        title="Data source notifications"
        className="relative w-10 h-10 flex items-center justify-center rounded-lg text-slate-400 hover:bg-slate-50 hover:text-slate-600 transition-colors"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {expired.length > 0 && (
          <span className="absolute top-1 right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
            {expired.length}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute left-full bottom-0 ml-2 w-80 bg-white border border-slate-200 rounded-xl shadow-xl z-50 p-2">
            <div className="px-3 py-2 border-b border-slate-100">
              <h3 className="text-sm font-semibold text-slate-900">Data source status</h3>
            </div>
            {expired.length === 0 ? (
              <p className="px-3 py-4 text-xs text-slate-400">All configured data sources are OK.</p>
            ) : (
              <div className="py-1">
                {expired.map((s) => (
                  <div key={s.source} className="flex items-start gap-3 rounded-lg px-3 py-2.5 hover:bg-slate-50">
                    <BrandLogo brandName={s.display_name} size={28} rounded="lg" className="shrink-0 bg-white ring-1 ring-slate-200" />
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-slate-900">{s.display_name} key expired</div>
                      <div className="text-xs text-red-600">
                        Expired {s.expired_at ? formatRelativeOrDate(s.expired_at) : ""}
                      </div>
                      <a
                        href={s.renew_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mt-1 inline-block text-xs font-semibold text-[#5B2C9D] hover:underline"
                      >
                        Renew on {s.display_name} &rarr;
                      </a>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
