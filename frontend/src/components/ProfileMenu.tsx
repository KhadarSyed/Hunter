import { useEffect, useRef, useState } from "react";
import { useAuth } from "../context/auth-context";
import { intelApi, type UserOrganizationRow } from "../services/intel-api";

type OrgChoice = { id: number; name: string; is_primary: boolean };

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
  const [orgs, setOrgs] = useState<OrgChoice[] | null>(null);
  const [switching, setSwitching] = useState<number | "all" | null>(null);
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
      // a Super Admin can work in any live organization; everyone else in their own and their memberships
      const load: Promise<OrgChoice[]> = user?.role === "super_admin"
        ? intelApi.listOrganizations().then((all) => all
            .filter((o) => !(o as { archived_at?: number | null }).archived_at)
            .map((o) => ({ id: o.id, name: o.name, is_primary: false })))
        : intelApi.listMyOrganizations().then((rows: UserOrganizationRow[]) => rows);
      load.then(setOrgs).catch(() => setOrgs([]));
    }
  }, [open, orgs, user?.role]);

  if (!user) return null;

  // the whole app reads the active org (projects, new projects, providers), so a full reload starts it clean
  const switchOrg = async (orgId: number | null) => {
    setSwitching(orgId ?? "all");
    setError("");
    try {
      await intelApi.setActiveOrg(orgId);
      window.location.assign("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not switch organization");
      setSwitching(null);
    }
  };

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
          {orgs && (orgs.length > 1 || user.role === "super_admin") && (
            <div className="px-1.5 py-2 border-b border-slate-100">
              <div className="px-1.5 text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1">
                Switch organization
              </div>
              <div className="max-h-48 space-y-0.5 overflow-y-auto" role="menu">
                {user.role === "super_admin" && (
                  <OrgRow name="All organizations" active={user.org_id == null} busy={switching === "all"}
                          onPick={() => switchOrg(null)} />
                )}
                {orgs.map((o) => (
                  <OrgRow key={o.id} name={o.name} hint={o.is_primary ? "Primary" : undefined}
                          active={user.org_id === o.id} busy={switching === o.id}
                          onPick={() => switchOrg(o.is_primary && user.role !== "super_admin" ? null : o.id)} />
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

function OrgRow({ name, hint, active, busy, onPick }:
  { name: string; hint?: string; active: boolean; busy: boolean; onPick: () => void }) {
  return (
    <button type="button" role="menuitemradio" aria-checked={active} disabled={active || busy} onClick={onPick}
            className={`flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left text-xs ${
              active ? "bg-[#5B2C9D10] font-semibold text-[#5B2C9D]" : "text-slate-600 hover:bg-slate-50"}`}>
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${active ? "bg-[#5B2C9D]" : "bg-slate-300"}`} aria-hidden />
      <span className="min-w-0 flex-1 truncate">{name}</span>
      {busy ? <span className="text-[10px] text-slate-400">Switching…</span>
        : hint && <span className="shrink-0 text-[10px] text-slate-400">{hint}</span>}
    </button>
  );
}
