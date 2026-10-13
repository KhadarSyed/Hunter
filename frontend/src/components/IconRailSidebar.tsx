import type { Page } from "../App";
import { ProfileMenu } from "./ProfileMenu";
import { NotificationBell } from "./NotificationBell";

/** Minimal icon-only sidebar for the landing/projects-list view (full
 * pipeline navigation only appears once a project is open — see
 * Sidebar.tsx). */
export function IconRailSidebar({ currentPage, onNavigate }: { currentPage: Page; onNavigate: (page: string) => void }) {
  const items: { page: Page; label: string; icon: JSX.Element }[] = [
    {
      page: "landing",
      label: "Home",
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
          <polyline points="9 22 9 12 15 12 15 22" />
        </svg>
      ),
    },
    {
      page: "projects",
      label: "Research Projects",
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
        </svg>
      ),
    },
    {
      page: "qc-projects",
      label: "QC Projects",
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
          <path d="M22 4L12 14.01l-3-3" />
        </svg>
      ),
    },
  ];

  return (
    <aside className="w-16 border-r border-slate-200 bg-white flex flex-col items-center shrink-0 py-4">
      <img src="/logo.png" alt="InfoVision Intelligence" className="h-8 w-8 rounded-md object-cover mb-6" />
      <nav className="flex-1 flex flex-col items-center gap-1.5">
        {items.map((item) => {
          const isActive =
            item.page === currentPage ||
            (item.page === "projects" && (currentPage === "new-project" || currentPage === "edit-project")) ||
            (item.page === "qc-projects" && (currentPage === "new-qc-project" || currentPage === "edit-qc-project"));
          return (
            <button
              key={item.page}
              onClick={() => onNavigate(item.page)}
              title={item.label}
              className={`w-10 h-10 flex items-center justify-center rounded-lg transition-colors ${
                isActive ? "bg-[#5B2C9D10] text-[#5B2C9D]" : "text-slate-400 hover:bg-slate-50 hover:text-slate-600"
              }`}
            >
              {item.icon}
            </button>
          );
        })}
      </nav>
      <div className="flex flex-col items-center gap-1">
        <NotificationBell />
        <ProfileMenu onNavigate={onNavigate} />
      </div>
    </aside>
  );
}
