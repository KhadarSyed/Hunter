/** Shown by a project page opened with no active project (a stale link, or a project that no longer exists). */
export function NoProjectSelected({ what, onNavigate }: { what: string; onNavigate: (page: string) => void }) {
  return (
    <div className="max-w-3xl mx-auto p-8">
      <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600">
        Open a project to see its {what}.{" "}
        <button type="button" onClick={() => onNavigate("projects")}
          className="font-medium text-[#5B2C9D] hover:underline">All projects</button>
      </div>
    </div>
  );
}
