import { Fragment, useState } from "react";
import type { Page } from "../App";
import { useProject } from "../context/project-context";
import { intelApi } from "../services/intel-api";
import { PencilIcon } from "./icons";
import { BrandLogo } from "./BrandLogo";
import { SettingsPanel } from "./SettingsPanel";

interface NavItem {
  page: Page | null;
  label: string;
  icon: string;
  comingSoon?: boolean;
  /** Group heading rendered above this item. */
  section?: string;
}

const RESEARCH_NAV: NavItem[] = [
  { page: "dashboard", label: "Dashboard", icon: "grid" },
  { page: "projects", label: "Projects", icon: "folder" },
  { page: "brief-scope-review", label: "Brief & Scope", icon: "file-text", section: "Scope" },
  { page: "background-research", label: "Background Research", icon: "globe" },
  { page: "search-strategy", label: "Search Strategy", icon: "search", section: "Research" },
  { page: "query-evaluation", label: "Query Evaluation", icon: "check-circle" },
  { page: "data-sources", label: "Data Sources", icon: "database" },
  { page: "research-plan", label: "Research Plan", icon: "columns" },
  { page: "research-execution", label: "Research Execution", icon: "play" },
  { page: "evidence-library", label: "Evidence Library", icon: "database" },
  { page: "analysis", label: "Analysis", icon: "lightbulb", section: "Analysis" },
  { page: "insights", label: "Insights", icon: "lightbulb" },
  { page: "storyline", label: "Storyline", icon: "file-text" },
  { page: "slide-intelligence", label: "Slide Intelligence", icon: "grid", section: "Deliver" },
  { page: "presentation-composer", label: "Presentation Composer", icon: "columns" },
  { page: "powerpoint-renderer", label: "PowerPoint Renderer", icon: "file-text" },
  { page: "word-renderer", label: "Word Renderer", icon: "file-text" },
  { page: "publishing-gateway", label: "Publishing Gateway", icon: "upload" },
  { page: "deliverables", label: "Deliverables", icon: "download" },
  { page: "pipeline-orchestrator", label: "Pipeline Orchestrator", icon: "settings", section: "Operations" },
];

const QC_NAV: NavItem[] = [
  { page: "qc-projects", label: "Projects", icon: "folder" },
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

export function Sidebar({ currentPage, onNavigate }: { currentPage: Page; onNavigate: (page: string) => void }) {
  const { activeProject, setActiveProject } = useProject();
  const isQCPage = QC_PAGES.has(currentPage);
  const isQC = isQCPage || activeProject?.project_type === "monitoring_qc";
  const navItems = isQC ? QC_NAV : RESEARCH_NAV;

  const accentColor = isQC ? "#0F7B6C" : "#5B2C9D";

  const [showSettings, setShowSettings] = useState(false);
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
    <aside className="w-56 border-r border-slate-200 bg-white flex flex-col shrink-0">
      <div className="h-14 flex items-center justify-between px-5 border-b border-slate-200">
        <button
          onClick={() => onNavigate("landing")}
          className="flex items-center gap-2.5 hover:opacity-80 transition-opacity"
        >
          <img
            src="/logo.png"
            alt="InfoVision Intelligence"
            className="h-7 w-7 rounded-md object-cover"
          />
          <span className="text-sm font-bold text-slate-900">InfoVision</span>
        </button>
        <button
          onClick={() => onNavigate("landing")}
          className="w-7 h-7 flex items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
          title="Home"
        >
          <NavIcon name="home" size={15} />
        </button>
      </div>

      {activeProject && (
        <div className="relative px-4 py-2.5 border-b border-slate-100">
          <div className="flex items-center gap-2">
            {activeProject.brand ? (
              <BrandLogo brandName={activeProject.brand} size={20} rounded="lg" className="bg-white ring-1 ring-slate-200" />
            ) : (
              <div
                className="w-5 h-5 rounded flex items-center justify-center text-white text-[10px] font-bold shrink-0"
                style={{ backgroundColor: accentColor }}
              >
                {isQC ? "Q" : "R"}
              </div>
            )}
            <span className="text-xs font-medium text-slate-700 truncate">{activeProject.name}</span>
            <button
              onClick={openEditPopover}
              className="ml-auto shrink-0 w-5 h-5 flex items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
              title="Edit project"
            >
              <PencilIcon size={12} />
            </button>
          </div>

          {editingProject && (
            <>
              <div className="fixed inset-0 z-40" onClick={closeEditPopover} />
              <div className="absolute left-4 top-full mt-1 w-64 bg-white border border-slate-200 rounded-lg shadow-lg z-50 p-3">
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

      {/* Workflow label */}
      <div className="px-5 pt-4 pb-1">
        <span
          className="text-[10px] font-semibold uppercase tracking-widest"
          style={{ color: accentColor }}
        >
          {isQC ? "Monitoring QC" : "Research"}
        </span>
      </div>

      <nav className="flex-1 py-1 px-3 space-y-0.5 overflow-y-auto">
        {navItems.map((item) => {
          const isActive =
            item.page === currentPage ||
            (item.page === "projects" && (currentPage === "new-project" || currentPage === "edit-project")) ||
            (item.page === "qc-projects" && (currentPage === "new-qc-project" || currentPage === "edit-qc-project")) ||
            (item.page === "brief-scope-review" && (currentPage === "brief-scope-review" || currentPage === "brief-analysis"));

          if (item.comingSoon) {
            return (
              <div
                key={item.label}
                className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-slate-300 cursor-default"
              >
                <NavIcon name={item.icon} size={15} />
                <span className="text-[13px]">{item.label}</span>
                <span className="ml-auto text-[9px] font-medium text-slate-300 bg-slate-100 px-1.5 py-0.5 rounded">
                  Soon
                </span>
              </div>
            );
          }

          return (
            <Fragment key={item.label}>
            {item.section && (
              <div className="px-3 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                {item.section}
              </div>
            )}
            <button
              onClick={() => item.page && onNavigate(item.page)}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition-colors ${
                isActive
                  ? "font-medium"
                  : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
              }`}
              style={isActive ? {
                backgroundColor: isQC ? "#0F7B6C10" : "#5B2C9D10",
                color: accentColor,
              } : undefined}
            >
              <NavIcon name={item.icon} size={15} />
              <span className="text-[13px]">{item.label}</span>
            </button>
            </Fragment>
          );
        })}
      </nav>

      <div className="p-3 border-t border-slate-100">
        <button
          onClick={() => onNavigate("settings")}
          className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-slate-500 hover:bg-slate-50 hover:text-slate-700 transition-colors"
        >
          <NavIcon name="user" size={15} />
          <span className="text-[13px]">My Account</span>
        </button>
        <button
          onClick={() => setShowSettings(true)}
          className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-slate-500 hover:bg-slate-50 hover:text-slate-700 transition-colors"
        >
          <NavIcon name="settings" size={15} />
          <span className="text-[13px]">Settings</span>
        </button>
      </div>
      {showSettings && <SettingsPanel onClose={() => setShowSettings(false)} />}
    </aside>
  );
}
