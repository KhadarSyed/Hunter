import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Icon } from "@iconify/react";
import { BrandLogo } from "../components/BrandLogo";
import { CountryFlag } from "../components/CountryFlag";
import { useAuth } from "../context/auth-context";
import { useProject, type ProjectType } from "../context/project-context";
import { intelApi, type BriefSource, type ProjectSummary } from "../services/intel-api";
import { formatRelativeOrDate } from "../utils/time";

interface Props {
  onNavigate: (page: string) => void;
  projectType?: ProjectType;
}

// Card header backgrounds, picked deterministically per brand (same brand → same colour).
const BRAND_GRADIENTS = [
  "from-emerald-950 via-emerald-900 to-slate-900",
  "from-rose-950 via-red-900 to-slate-900",
  "from-slate-900 via-indigo-950 to-slate-800",
  "from-teal-950 via-teal-900 to-slate-900",
  "from-zinc-900 via-neutral-800 to-zinc-700",
  "from-amber-950 via-orange-900 to-slate-900",
];
const NO_BRAND_GRADIENT = "from-violet-500 via-purple-500 to-indigo-700";

function gradientFor(brand: string): string {
  let h = 0;
  for (const ch of brand.toLowerCase()) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return BRAND_GRADIENTS[h % BRAND_GRADIENTS.length];
}

// How the brief was provided: uploaded file type or pasted text.
const BRIEF_SOURCES: Record<string, { label: string; icon: string }> = {
  pdf: { label: "PDF", icon: "vscode-icons:file-type-pdf2" },
  docx: { label: "Word", icon: "vscode-icons:file-type-word" },
  doc: { label: "Word", icon: "vscode-icons:file-type-word" },
  pptx: { label: "PowerPoint", icon: "vscode-icons:file-type-powerpoint" },
  ppt: { label: "PowerPoint", icon: "vscode-icons:file-type-powerpoint" },
  xlsx: { label: "Excel", icon: "vscode-icons:file-type-excel" },
  xls: { label: "Excel", icon: "vscode-icons:file-type-excel" },
  txt: { label: "TXT file", icon: "vscode-icons:file-type-text" },
  text: { label: "Text", icon: "lucide:text-cursor-input" },
};

function BriefSourceChip({ source }: { source: BriefSource | null }) {
  if (!source) return null;
  const meta = BRIEF_SOURCES[source.type] ?? { label: source.type.toUpperCase(), icon: "lucide:file" };
  const title = source.file_name ? `Brief uploaded as ${source.file_name}` : "Brief entered as text";
  return (
    <span
      title={title}
      className="absolute left-3 top-3 inline-flex items-center gap-1.5 rounded-full bg-white/90 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-slate-800 shadow-sm backdrop-blur"
    >
      <Icon icon={meta.icon} width={14} className={source.type === "text" ? "text-slate-500" : ""} aria-hidden />
      {meta.label}
    </span>
  );
}

function editedAgo(ts: number): string {
  return `Edited ${formatRelativeOrDate(ts)}`;
}

interface ProjectCardProps {
  project: ProjectSummary;
  onOpen: () => void;
  onEdit: () => void;
  onDelete: () => void;
  selected: boolean;
  onToggleSelect: () => void;
}

function ProjectCard({ project, onOpen, onEdit, onDelete, selected, onToggleSelect }: ProjectCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0 });
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const brand = project.brand?.trim() ?? "";

  const openMenu = () => {
    const rect = menuButtonRef.current?.getBoundingClientRect();
    if (rect) setMenuPos({ top: rect.bottom + 4, left: rect.right - 224 });
    setMenuOpen((o) => !o);
  };

  return (
    <div className={`group relative flex flex-col overflow-hidden rounded-3xl bg-white shadow-sm ring-1 transition-all hover:-translate-y-0.5 hover:shadow-xl ${
      selected ? "ring-2 ring-[#5B2C9D]" : "ring-slate-900/5"
    }`}>
      <button onClick={onOpen} className="relative h-48 w-full overflow-hidden text-left" aria-label={`Open ${project.project_name}`}>
        <div className={`absolute inset-0 bg-gradient-to-br ${brand ? gradientFor(brand) : NO_BRAND_GRADIENT}`} />
        <div className="absolute inset-0 opacity-20 [background-image:radial-gradient(white_1px,transparent_1px)] [background-size:14px_14px]" />
        <BriefSourceChip source={project.brief_source} />
        {brand && (
          <span className="absolute right-3 top-3 inline-flex items-center gap-1.5 rounded-full bg-black/60 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-white backdrop-blur">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            {brand}
          </span>
        )}
        <div className="absolute inset-0 flex items-center justify-center">
          {brand ? (
            <div className="flex h-20 w-20 items-center justify-center rounded-2xl bg-white shadow-lg transition-transform group-hover:scale-105">
              <BrandLogo brandName={brand} size={48} rounded="lg" />
            </div>
          ) : (
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-white/20 text-white backdrop-blur">
              <Icon icon="lucide:folder" width={28} />
            </div>
          )}
        </div>
      </button>

      <div className="flex flex-1 flex-col px-5 pt-4 pb-4">
        <div className="flex items-start gap-2">
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggleSelect}
            onClick={(e) => e.stopPropagation()}
            aria-label={`Select ${project.project_name}`}
            className="mt-1 h-4 w-4 shrink-0 rounded border-slate-300 text-[#5B2C9D] focus:ring-[#5B2C9D]/30"
          />
          <button onClick={onOpen} className="min-w-0 flex-1 text-left">
            <h3 className="truncate text-base font-bold text-slate-900" title={project.project_name}>
              {project.project_name}
            </h3>
          </button>
          <div className="relative">
            <button
              ref={menuButtonRef}
              onClick={openMenu}
              className="rounded-md px-1.5 py-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              aria-label="Project actions"
            >
              <Icon icon="lucide:more-horizontal" width={18} />
            </button>
            {menuOpen && createPortal(
              <>
                <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
                <div
                  role="menu"
                  style={{ position: "fixed", top: menuPos.top, left: menuPos.left }}
                  className="z-50 w-56 overflow-hidden rounded-2xl border border-slate-100 bg-white p-1.5 shadow-xl"
                >
                  <button
                    role="menuitem"
                    onClick={() => { setMenuOpen(false); onEdit(); }}
                    className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-[15px] font-medium text-slate-700 hover:bg-slate-50"
                  >
                    <Icon icon="lucide:pencil" width={18} className="text-slate-500" /> Edit project
                  </button>
                  <button
                    role="menuitem"
                    onClick={() => { setMenuOpen(false); onDelete(); }}
                    className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-[15px] font-semibold text-red-600 hover:bg-red-50"
                  >
                    <Icon icon="lucide:trash-2" width={18} /> Delete
                  </button>
                </div>
              </>,
              document.body
            )}
          </div>
        </div>
        <p className="mt-2 line-clamp-3 text-sm leading-relaxed text-slate-600">
          {project.description || <span className="text-slate-400">No brief added yet.</span>}
        </p>
        <div className="mt-auto flex items-center justify-between gap-2 border-t border-slate-100 pt-3 text-xs text-slate-500">
          <span>{editedAgo(project.updated_at)}</span>
          <CountryFlag country={project.geography} size={16} showLabel className="truncate" />
        </div>
      </div>
    </div>
  );
}

/** Project list ("All Projects") — entry point after the landing page. */
export function ProjectsPage({ onNavigate, projectType = "research" }: Props) {
  const isQC = projectType === "monitoring_qc";
  const { user } = useAuth();
  const { activeProject, setActiveProject, clearProject } = useProject();
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [ownerNames, setOwnerNames] = useState<Record<number, string>>({});
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [pendingDelete, setPendingDelete] = useState<ProjectSummary[] | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const searchRef = useRef<HTMLInputElement>(null);
  const selectAllRef = useRef<HTMLInputElement>(null);

  const load = () => {
    setError("");
    setProjects(null);
    intelApi
      .listProjects(projectType)
      .then(setProjects)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load projects"));
  };
  useEffect(load, [projectType]);

  // Admins see every project in their org grouped by owning Analyser — resolve
  // owner ids to display names once (the project list itself is already scoped
  // server-side by role/org, see intelApi.listProjects's backend).
  useEffect(() => {
    if (user?.role !== "admin") return;
    intelApi.listUsers().then((users) => {
      setOwnerNames(Object.fromEntries(users.map((u) => [u.id, u.display_name])));
    }).catch(() => {});
  }, [user?.role]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!projects || !q) return projects ?? [];
    return projects.filter((p) =>
      [p.project_name, p.description, p.brand ?? "", p.client].some((f) => f.toLowerCase().includes(q))
    );
  }, [projects, query]);

  // Grouped by owning Analyser, Admin-only (Super Admin and Analyser keep the flat grid —
  // an Analyser only ever sees their own projects anyway, so grouping adds nothing there).
  const ownerGroups = useMemo(() => {
    if (user?.role !== "admin") return null;
    const groups = new Map<number, ProjectSummary[]>();
    for (const p of filtered) {
      const ownerId = p.owner_user_id ?? 0;
      const bucket = groups.get(ownerId);
      if (bucket) bucket.push(p);
      else groups.set(ownerId, [p]);
    }
    return groups;
  }, [filtered, user?.role]);

  const select = (p: ProjectSummary, page: string) => {
    setActiveProject({ id: p.id, name: p.project_name, project_type: (p.project_type as ProjectType) || projectType, brand: p.brand });
    onNavigate(page);
  };
  const toggleSelected = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const clearSelection = () => setSelected(new Set());
  const allSelected = filtered.length > 0 && filtered.every((p) => selected.has(p.id));
  const someSelected = selected.size > 0 && !allSelected;
  const toggleSelectAll = () => {
    setSelected(allSelected ? new Set() : new Set(filtered.map((p) => p.id)));
  };
  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = someSelected;
  }, [someSelected]);
  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    setDeleteError("");
    const deletedIds: number[] = [];
    for (const p of pendingDelete) {
      try {
        await intelApi.deleteProject(p.id);
        deletedIds.push(p.id);
      } catch (e) {
        setDeleteError(e instanceof Error ? e.message : `Could not delete "${p.project_name}"`);
        break;
      }
    }
    setProjects((list) => (list ?? []).filter((p) => !deletedIds.includes(p.id)));
    if (activeProject && deletedIds.includes(activeProject.id)) clearProject();
    setSelected((prev) => {
      const next = new Set(prev);
      deletedIds.forEach((id) => next.delete(id));
      return next;
    });
    if (deletedIds.length === pendingDelete.length) setPendingDelete(null);
    setDeleting(false);
  };
  const closeDelete = () => {
    if (deleting) return;
    setPendingDelete(null);
    setDeleteError("");
  };

  const openPage = isQC ? "qc-upload" : "dashboard";
  const newPage = isQC ? "new-qc-project" : "new-project";
  const editPage = isQC ? "edit-qc-project" : "edit-project";

  return (
    <div className="flex h-full flex-col bg-gradient-to-br from-slate-100 via-slate-50 to-violet-50">
      <div className="shrink-0 px-8 pt-8">
      <nav className="text-sm text-slate-500">
        {isQC ? "Monitoring QC" : "Research"} <span className="mx-2 text-slate-300">›</span>
        <span className="font-semibold text-slate-900">Projects</span>
      </nav>

      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900">All Projects</h1>
          <p className="mt-1 text-sm text-slate-600">Manage, monitor, and explore media measurement and brand intelligence projects.</p>
        </div>
        <div className="flex items-center gap-3">
          {projects && (
            <span className="rounded-full bg-white px-3 py-1.5 text-sm font-semibold text-slate-700 shadow-sm ring-1 ring-slate-900/5">
              {projects.length} {projects.length === 1 ? "Project" : "Projects"}
            </span>
          )}
          <button
            onClick={() => onNavigate(newPage)}
            className="inline-flex items-center gap-2 rounded-full bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white shadow-md transition-colors hover:bg-slate-800"
          >
            <Icon icon="lucide:plus" width={16} /> New Project
          </button>
        </div>
      </div>

      <div className="relative mt-6 max-w-xl">
        <Icon icon="lucide:search" width={16} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" />
        <input
          ref={searchRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search projects by title, description, or brand..."
          className="w-full rounded-2xl border border-slate-200 bg-white py-3 pl-11 pr-16 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-violet-300 focus:outline-none focus:ring-2 focus:ring-violet-500/20"
        />
        <kbd className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium text-slate-500">Ctrl K</kbd>
      </div>

      {projects !== null && projects.length > 0 && (
        <div className="mt-4 flex items-center justify-between gap-4">
          <label className="inline-flex items-center gap-2 text-sm font-medium text-slate-600">
            <input
              ref={selectAllRef}
              type="checkbox"
              checked={allSelected}
              onChange={toggleSelectAll}
              aria-label="Select all projects"
              className="h-4 w-4 rounded border-slate-300 text-[#5B2C9D] focus:ring-[#5B2C9D]/30"
            />
            Select all
          </label>
          {selected.size > 0 && (
            <div className="flex items-center gap-2 rounded-xl border border-[#5B2C9D]/20 bg-[#5B2C9D]/5 px-3 py-1.5">
              <span className="text-sm font-medium text-slate-700">{selected.size} selected</span>
              <button onClick={clearSelection} className="rounded-lg px-2.5 py-1 text-sm font-medium text-slate-600 hover:bg-white">
                Clear
              </button>
              <button
                onClick={() => setPendingDelete((projects ?? []).filter((p) => selected.has(p.id)))}
                className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-2.5 py-1 text-sm font-semibold text-white hover:bg-red-700"
              >
                <Icon icon="lucide:trash-2" width={14} /> Delete selected
              </button>
            </div>
          )}
        </div>
      )}
      </div>

      <div className="flex-1 overflow-y-auto px-8 pb-8">
      {error ? (
        <div className="mt-10 rounded-2xl border border-red-200 bg-red-50 p-6 text-sm text-red-700">
          {error} <button onClick={load} className="ml-2 font-semibold underline">Retry</button>
        </div>
      ) : projects === null ? (
        <div className="mt-8 grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-6">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="h-[380px] animate-pulse rounded-3xl bg-white/70 ring-1 ring-slate-900/5" />
          ))}
        </div>
      ) : projects.length === 0 ? (
        <div className="mt-10 flex flex-col items-center rounded-3xl border-2 border-dashed border-slate-300 bg-white/60 px-6 py-16 text-center">
          <Icon icon="lucide:folder-open" width={36} className="text-slate-400" />
          <p className="mt-3 text-base font-semibold text-slate-700">Currently no projects listed.</p>
          <p className="mt-1 text-sm text-slate-500">Create a project and analyse a client brief to get started.</p>
          <button
            onClick={() => onNavigate(newPage)}
            className="mt-5 inline-flex items-center gap-2 rounded-full bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white hover:bg-slate-800"
          >
            <Icon icon="lucide:plus" width={16} /> New Project
          </button>
        </div>
      ) : filtered.length === 0 ? (
        <p className="mt-10 text-sm text-slate-500">No projects match “{query}”.</p>
      ) : ownerGroups ? (
        <div className="mt-8 space-y-10">
          {Array.from(ownerGroups.entries()).map(([ownerId, group]) => (
            <div key={ownerId}>
              <h2 className="mb-3 text-sm font-semibold text-slate-700">
                {ownerNames[ownerId] ?? "Unassigned"}
              </h2>
              <div className="grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-6">
                {group.map((p) => (
                  <ProjectCard
                    key={p.id}
                    project={p}
                    onOpen={() => select(p, openPage)}
                    onEdit={() => select(p, editPage)}
                    onDelete={() => setPendingDelete([p])}
                    selected={selected.has(p.id)}
                    onToggleSelect={() => toggleSelected(p.id)}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="mt-8 grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-6">
          {filtered.map((p) => (
            <ProjectCard
              key={p.id}
              project={p}
              onOpen={() => select(p, openPage)}
              onEdit={() => select(p, editPage)}
              onDelete={() => setPendingDelete([p])}
              selected={selected.has(p.id)}
              onToggleSelect={() => toggleSelected(p.id)}
            />
          ))}
          <button
            onClick={() => onNavigate(newPage)}
            className="flex min-h-[380px] flex-col items-center justify-center gap-2 rounded-3xl border-2 border-dashed border-slate-300 bg-white/40 text-slate-500 transition-colors hover:border-violet-400 hover:text-violet-600"
          >
            <Icon icon="lucide:plus-circle" width={32} />
            <span className="text-sm font-semibold">Create new project</span>
          </button>
        </div>
      )}
      </div>

      {pendingDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={closeDelete}>
          <div
            role="alertdialog"
            aria-labelledby="delete-title"
            className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex h-11 w-11 items-center justify-center rounded-full bg-red-50 text-red-600">
              <Icon icon="lucide:trash-2" width={20} />
            </div>
            <h2 id="delete-title" className="mt-4 text-lg font-bold text-slate-900">
              {pendingDelete.length === 1 ? "Delete project?" : `Delete ${pendingDelete.length} projects?`}
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-slate-600">
              {pendingDelete.length === 1 ? (
                <span className="font-semibold text-slate-800">{pendingDelete[0].project_name}</span>
              ) : (
                <span className="font-semibold text-slate-800">{pendingDelete.length} selected projects</span>
              )}{" "}
              and all of their brief, research, strategy, evidence, insights and deliverables will be
              permanently deleted. This can’t be undone.
            </p>
            {deleteError && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{deleteError}</p>}
            <div className="mt-6 flex justify-end gap-2">
              <button
                onClick={closeDelete}
                disabled={deleting}
                className="rounded-lg px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                disabled={deleting}
                className="inline-flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-60"
              >
                <Icon icon={deleting ? "lucide:loader-2" : "lucide:trash-2"} width={16} className={deleting ? "animate-spin" : ""} />
                {deleting ? "Deleting..." : pendingDelete.length === 1 ? "Delete project" : `Delete ${pendingDelete.length} projects`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
