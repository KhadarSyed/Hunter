import { useState } from "react";
import type { Page } from "../App";
import { useProject } from "../context/project-context";
import { intelApi } from "../services/intel-api";
import { PencilIcon } from "./icons";
import { BrandLogo } from "./BrandLogo";
import { ProfileMenu } from "./ProfileMenu";
import { ProjectSwitcher } from "./ProjectSwitcher";
import { NotificationBell } from "./NotificationBell";

interface NavItem {
  page: Page;
  label: string;
  icon: string;
}

const RESEARCH_NAV: NavItem[] = [
  { page: "dashboard", label: "Dashboard", icon: "grid" },
  { page: "pipeline-orchestrator", label: "Pipeline Orchestrator", icon: "settings" },
];

const QC_NAV: NavItem[] = [
  { page: "qc-upload", label: "Upload Report", icon: "upload" },
  { page: "qc-results", label: "QC Results", icon: "check-circle" },
  { page: "qc-export", label: "Export", icon: "download" },
];

const QC_PAGES = new Set<string>(["qc-projects", "new-qc-project", "edit-qc-project", "qc-upload", "qc-field-mapping", "qc-results", "qc-export"]);

function NavIcon({ name, size = 16 }: { name: string; size?: number }) {
  const props = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

  switch (name) {
    case "grid": return <svg {...props}><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></svg>;
    case "folder": return <svg {...props}><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" /></svg>;
    case "file-text": return <svg {...props}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /></svg>;
    case "globe": return <svg {...props}><circle cx="12" cy="12" r="10" /><line x1="2" y1="12" x2="22" y2="12" /><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" /></svg>;
    case "search": return <svg {...props}><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>;
    case "database": return <svg {...props}><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" /><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" /></svg>;
    case "lightbulb": return <svg {...props}><path d="M9 18h6" /><path d="M10 22h4" /><path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z" /></svg>;
    case "play": return <svg {...props}><polygon points="5 3 19 12 5 21 5 3" /></svg>;
    case "check-circle": return <svg {...props}><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><path d="M22 4L12 14.01l-3-3" /></svg>;
    case "download": return <svg {...props}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>;
    case "upload": return <svg {...props}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" /></svg>;
    case "columns": return <svg {...props}><path d="M12 3h7a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-7m0-18H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h7m0-18v18" /></svg>;
    case "home": return <svg {...props}><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></svg>;
    case "settings": return <svg {...props}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.26.6.86 1.02 1.51 1.08H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>;
    case "user": return <svg {...props}><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>;
    default: return null;
  }
}

/** Full pipeline-stage navigation, icon-only (matches the landing view's
 * IconRailSidebar look), shown only once a project is open — see
 * App.tsx's BROWSING_PAGES. */
export function Sidebar({ currentPage, onNavigate }: { currentPage: Page; onNavigate: (page: string) => void }) {
  const { activeProject, setActiveProject } = useProject();
  const isQCPage = QC_PAGES.has(currentPage);
  const isQC = isQCPage || activeProject?.project_type === "monitoring_qc";
  const navItems = isQC ? QC_NAV : RESEARCH_NAV;

  const accentColor = isQC ? "#0F7B6C" : "#5B2C9D";

  const [editingProject, setEditingProject] = useState(false);
  const [editName, setEditName] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [editNameError, setEditNameError] = useState("");

  const openEditPopover = () => {
    if (!activeProject) return;
    setEditName(activeProject.name);
    setEditNameError("");
    setEditingProject(true);
  };

  const closeEditPopover = () => setEditingProject(false);

  const handleSaveName = async () => {
    if (!activeProject || !editName.trim()) return;
    setSavingName(true);
    setEditNameError("");
    try {
      const updated = await intelApi.updateProject(activeProject.id, { project_name: editName.trim() });
      setActiveProject({ ...activeProject, name: updated.project_name });
      setEditingProject(false);
    } catch (err) {
      setEditNameError(err instanceof Error ? err.message : "Failed to save project name");
    } finally {
      setSavingName(false);
    }
  };

  return (
    <aside className="w-16 border-r border-slate-200 bg-white flex flex-col items-center shrink-0 py-4">
      <button onClick={() => onNavigate("landing")} className="hover:opacity-80 transition-opacity mb-3" title="Home">
        <img src="/logo.png" alt="InfoVision Intelligence" className="h-8 w-8 rounded-md object-cover" />
      </button>

      {activeProject && (
        <div className="relative mb-3">
          <button
            onClick={openEditPopover}
            title={`${activeProject.name} — click to rename`}
            className="block"
          >
            {activeProject.brand ? (
              <BrandLogo brandName={activeProject.brand} size={32} rounded="lg" className="bg-white ring-1 ring-slate-200" />
            ) : (
              <div
                className="w-8 h-8 rounded-lg flex items-center justify-center text-white text-xs font-bold shrink-0"
                style={{ backgroundColor: accentColor }}
              >
                {isQC ? "Q" : "R"}
              </div>
            )}
          </button>

          {editingProject && (
            <>
              <div className="fixed inset-0 z-40" onClick={closeEditPopover} />
              <div className="absolute left-full top-0 ml-2 w-64 bg-white border border-slate-200 rounded-lg shadow-lg z-50 p-3">
                <label className="block text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-1">
                  Project name
                </label>
                <input
                  autoFocus
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleSaveName();
                    if (e.key === "Escape") closeEditPopover();
                  }}
                  className="w-full text-xs px-2 py-1.5 border border-slate-200 rounded-md focus:outline-none focus:ring-1"
                  style={{ ["--tw-ring-color" as string]: accentColor }}
                />
                {editNameError && (
                  <div className="text-[11px] text-red-600 mt-1">{editNameError}</div>
                )}
                <div className="flex items-center justify-between mt-2.5">
                  <button
                    onClick={() => onNavigate("brief-scope-review")}
                    className="text-[11px] font-medium hover:underline"
                    style={{ color: accentColor }}
                  >
                    Edit spec &rarr;
                  </button>
                  <div className="flex items-center gap-1.5">
                    <button
                      onClick={closeEditPopover}
                      className="text-[11px] px-2 py-1 rounded-md text-slate-500 hover:bg-slate-100"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleSaveName}
                      disabled={savingName || !editName.trim()}
                      className="text-[11px] px-2.5 py-1 rounded-md text-white font-medium disabled:opacity-50"
                      style={{ backgroundColor: accentColor }}
                    >
                      {savingName ? "Saving..." : "Save"}
                    </button>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      <ProjectSwitcher onNavigate={onNavigate} />
      <nav className="flex-1 flex flex-col items-center gap-1 overflow-y-auto">
        {navItems.map((item) => {
          const isActive = item.page === currentPage;

          return (
            <button
              key={item.page}
              onClick={() => onNavigate(item.page)}
              title={item.label}
              className={`w-10 h-10 flex items-center justify-center rounded-lg transition-colors ${
                isActive ? "" : "text-slate-400 hover:bg-slate-50 hover:text-slate-600"
              }`}
              style={isActive ? { backgroundColor: isQC ? "#0F7B6C10" : "#5B2C9D10", color: accentColor } : undefined}
            >
              <NavIcon name={item.icon} size={17} />
            </button>
          );
        })}
      </nav>

      <div className="flex flex-col items-center gap-1 pt-2 border-t border-slate-100 w-full">
        <NotificationBell />
        <ProfileMenu onNavigate={onNavigate} />
      </div>
    </aside>
  );
}
