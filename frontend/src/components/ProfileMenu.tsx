import { useEffect, useRef, useState } from "react";
import { useAuth } from "../context/auth-context";
import { intelApi, type UserOrganizationRow } from "../services/intel-api";

const ROLE_LABELS: Record<string, string> = {
  super_admin: "Super Admin",
  admin: "Admin",
  analyser: "Analyser",
};

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return (parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "");
}

function Avatar({ avatarUrl, name, size = 32 }: { avatarUrl: string | null; name: string; size?: number }) {
  if (avatarUrl) {
    return (
      <img
        src={avatarUrl}
        alt=""
        className="rounded-full object-cover shrink-0"
        style={{ width: size, height: size }}
      />
    );
  }
  return (
    <div
      className="rounded-full bg-[#5B2C9D] text-white flex items-center justify-center font-semibold shrink-0"
      style={{ width: size, height: size, fontSize: size * 0.4 }}
    >
      {initials(name).toUpperCase() || "?"}
    </div>
  );
}

/** Profile avatar button + dropdown: name/email/role/org, Settings, Logout.
 * Used in both the icon-rail sidebar (landing view) and the full pipeline
 * sidebar's footer. */
export function ProfileMenu({ onNavigate }: { onNavigate: (page: string) => void }) {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const [orgs, setOrgs] = useState<UserOrganizationRow[] | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  // Fetched lazily on first open rather than on mount — this dropdown renders in every
  // sidebar instance on every page, so an eager fetch would fire constantly unused.
  useEffect(() => {
    if (open && orgs === null) {
      intelApi.listMyOrganizations().then(setOrgs).catch(() => setOrgs([]));
    }
  }, [open, orgs]);

  if (!user) return null;

  const handleLogout = async () => {
    setError("");
    try {
      await logout();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Logout failed");
    }
  };

  return (
    <div className="relative" ref={containerRef}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center justify-center hover:opacity-80 transition-opacity"
        title={user.display_name}
      >
        <Avatar avatarUrl={user.avatar_url} name={user.display_name} />
      </button>

      {open && (
        <div
          className="absolute bottom-full mb-2 left-0 w-64 bg-white border border-slate-200 rounded-xl shadow-lg z-50 overflow-hidden"
        >
          <div className="p-3 border-b border-slate-100 flex items-center gap-2.5">
            <Avatar avatarUrl={user.avatar_url} name={user.display_name} size={36} />
            <div className="min-w-0">
              <div className="text-sm font-semibold text-slate-900 truncate">{user.display_name}</div>
              <div className="text-xs text-slate-500 truncate">{user.email}</div>
            </div>
          </div>
          <div className="px-3 py-2 border-b border-slate-100 flex items-center gap-2 text-xs text-slate-500">
            <span className="px-1.5 py-0.5 rounded bg-slate-100 font-medium text-slate-700">
              {ROLE_LABELS[user.role] ?? user.role}
            </span>
            {user.org_name && <span className="truncate">{user.org_name}</span>}
          </div>
          {orgs && orgs.length > 0 && (
            <div className="px-3 py-2 border-b border-slate-100">
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1">
                Organizations
              </div>
              <div className="space-y-0.5">
                {orgs.map((o) => (
                  <div key={o.id} className="flex items-center justify-between text-xs text-slate-600">
                    <span className="truncate">{o.name}</span>
                    {o.is_primary && (
                      <span className="shrink-0 ml-2 text-[10px] text-slate-400">Primary</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
          {error && <div className="px-3 py-1.5 text-[11px] text-red-600">{error}</div>}
          <div className="p-1.5">
            <button
              onClick={() => { setOpen(false); onNavigate("settings"); }}
              className="w-full text-left px-2.5 py-1.5 text-sm text-slate-700 rounded-md hover:bg-slate-50"
            >
              Settings
            </button>
            <button
              onClick={handleLogout}
              className="w-full text-left px-2.5 py-1.5 text-sm text-red-600 rounded-md hover:bg-red-50"
            >
              Logout
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
