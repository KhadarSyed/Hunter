import { useEffect, useState } from "react";
import { useProject, type ProjectType } from "../context/project-context";
import { intelApi, type ProjectSummary } from "../services/intel-api";
import { BrandLogo } from "./BrandLogo";
import { formatRelativeOrDate } from "../utils/time";

const MAX_LISTED = 20;
const VISIBLE_ROWS = 10;
const ROW_HEIGHT_PX = 60;
const LABEL_MAX_CHARS = 20;

function truncateLabel(name: string): string {
  return name.length > LABEL_MAX_CHARS ? `${name.slice(0, LABEL_MAX_CHARS)}…` : name;
}

/** Quick project switcher, anchored above Dashboard in the full pipeline
 * sidebar: a drawer that slides out from the left edge (next to the icon
 * rail) listing the most recently updated projects (same type as the
 * active one), and slides back in on selection or close. */
export function ProjectSwitcher({ onNavigate }: { onNavigate: (page: string) => void }) {
  const { activeProject, setActiveProject } = useProject();
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);

  useEffect(() => {
    if (!open || projects) return;
    intelApi.listProjects(activeProject?.project_type)
      .then((list) => setProjects([...list].sort((a, b) => b.updated_at - a.updated_at)))
      .catch(() => setProjects([]));
  }, [open, projects, activeProject?.project_type]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const select = (p: ProjectSummary) => {
    setOpen(false);
    setActiveProject({
      id: p.id, name: p.project_name,
      project_type: (p.project_type as ProjectType) || "research",
      brand: p.brand,
    });
    onNavigate("dashboard");
  };

  return (
    <>
      <button
        onClick={() => setOpen((o) => !o)}
        title="Switch project"
        className="w-10 h-10 flex items-center justify-center rounded-lg text-slate-400 hover:bg-slate-50 hover:text-slate-600 transition-colors"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
        </svg>
      </button>

      {/* Backdrop — fades in/out, click closes the drawer. */}
      <div
        onClick={() => setOpen(false)}
        className={`fixed inset-0 bg-slate-900/20 z-40 transition-opacity duration-300 ${
          open ? "opacity-100" : "opacity-0 pointer-events-none"
        }`}
      />

      {/* Drawer — floats next to the icon rail, sized to its content (header +
          up to VISIBLE_ROWS rows, never the full viewport height). Slides in
          from the left, slides back out on close/select. Always mounted so
          the exit transition plays; pointer-events disabled while hidden. */}
      <div
        className={`fixed left-16 top-4 w-80 bg-white rounded-2xl shadow-2xl ring-1 ring-slate-200 z-50 flex flex-col transition-transform duration-300 ease-out ${
          open ? "translate-x-0" : "-translate-x-[calc(100%+4rem)] pointer-events-none"
        }`}
        style={{ maxHeight: `calc(100vh - 2rem)` }}
      >
        <div className="px-4 py-4 border-b border-slate-100 flex items-center justify-between shrink-0">
          <h2 className="text-sm font-semibold text-slate-900">Switch project</h2>
          <button onClick={() => setOpen(false)} className="text-slate-400 hover:text-slate-600" title="Close">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <div
          className="overflow-y-auto divide-y divide-slate-100 rounded-b-2xl"
          style={{ maxHeight: VISIBLE_ROWS * ROW_HEIGHT_PX }}
        >
          {projects === null ? (
            <div className="px-4 py-4 text-sm text-slate-400">Loading…</div>
          ) : projects.length === 0 ? (
            <div className="px-4 py-4 text-sm text-slate-400">No projects found.</div>
          ) : (
            projects.slice(0, MAX_LISTED).map((p) => (
              <button
                key={p.id}
                onClick={() => select(p)}
                style={{ height: ROW_HEIGHT_PX }}
                className={`w-full flex items-center gap-3 px-4 text-left hover:bg-slate-50 ${
                  p.id === activeProject?.id ? "bg-[#5B2C9D08]" : ""
                }`}
              >
                {p.brand ? (
                  <BrandLogo brandName={p.brand} size={28} rounded="lg" className="shrink-0 bg-white ring-1 ring-slate-200" />
                ) : (
                  <div className="w-7 h-7 rounded-lg bg-slate-100 text-slate-500 flex items-center justify-center text-xs font-bold shrink-0">
                    {p.project_name.charAt(0).toUpperCase() || "?"}
                  </div>
                )}
                <span className="flex-1 min-w-0 flex flex-col gap-0.5">
                  <span
                    className={`truncate text-sm ${
                      p.id === activeProject?.id ? "text-[#5B2C9D] font-medium" : "text-slate-700"
                    }`}
                    title={p.project_name}
                  >
                    {truncateLabel(p.project_name)}
                  </span>
                  <span className="text-[11px] text-slate-400 tabular-nums">
                    {p.created_at === p.updated_at ? "Created" : "Updated"} {formatRelativeOrDate(p.updated_at)}
                  </span>
                </span>
              </button>
            ))
          )}
        </div>
      </div>
    </>
  );
}
