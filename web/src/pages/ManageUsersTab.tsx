import { useEffect, useState } from "react";
import { useAuth } from "../context/auth-context";
import { intelApi, type AuthOrganizationRow, type AuthUserRow } from "../services/intel-api";
import { formatRelativeOrDate } from "../utils/time";

/** Clipboard-copy affordance for a one-time plaintext credential (new-user or reset temp
 * password) — shown once in a dismissible banner, never persisted beyond this render. */
function CredentialBanner({ email, tempPassword, onDismiss }: { email: string; tempPassword: string; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3">
      <div className="text-sm text-emerald-800">
        Temp password for <span className="font-semibold">{email}</span>:{" "}
        <span className="font-mono font-semibold">{tempPassword}</span>
        <span className="block text-xs text-emerald-700 mt-0.5">Share this with the user now — it won't be shown again.</span>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={() => { navigator.clipboard.writeText(tempPassword).catch(() => {}); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
          className="rounded-lg border border-emerald-300 bg-white px-2.5 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-100"
        >
          {copied ? "Copied" : "Copy"}
        </button>
        <button onClick={onDismiss} className="text-emerald-600 hover:text-emerald-800">✕</button>
      </div>
    </div>
  );
}

export function ManageUsersTab() {
  const { user: currentUser } = useAuth();
  const isSuperAdmin = currentUser?.role === "super_admin";

  const [users, setUsers] = useState<AuthUserRow[]>([]);
  const [orgs, setOrgs] = useState<AuthOrganizationRow[]>([]);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<"analyser" | "admin" | "super_admin">("analyser");
  const [orgId, setOrgId] = useState<number | "">("");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [resettingId, setResettingId] = useState<number | null>(null);
  const [credential, setCredential] = useState<{ email: string; tempPassword: string } | null>(null);

  // Super Admin: the Organization dropdown both picks which org a new user joins AND
  // filters the list below to that org — "" means "all organizations" for viewing, but
  // a concrete org must be picked before Create is enabled (see createDisabled).
  const load = () => intelApi.listUsers(isSuperAdmin && orgId !== "" ? Number(orgId) : undefined).then(setUsers);
  useEffect(() => { load(); }, [isSuperAdmin, orgId]);
  useEffect(() => {
    if (isSuperAdmin) intelApi.listOrganizations().then(setOrgs);
  }, [isSuperAdmin]);

  const createDisabled = creating || !email.trim() || !displayName.trim() || (isSuperAdmin && orgId === "");

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (createDisabled) return;
    setCreating(true);
    try {
      const created = await intelApi.createUser(email.trim(), displayName.trim(), role, isSuperAdmin ? Number(orgId) : undefined);
      setCredential({ email: created.email, tempPassword: created.temp_password });
      setEmail(""); setDisplayName(""); setRole("analyser");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create user");
    } finally {
      setCreating(false);
    }
  };

  const handleResetPassword = async (u: AuthUserRow) => {
    setResettingId(u.id);
    setError(null);
    try {
      const res = await intelApi.resetUserPassword(u.id);
      setCredential({ email: u.email, tempPassword: res.temp_password });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset password");
    } finally {
      setResettingId(null);
    }
  };

  return (
    <div className="space-y-6">
      {credential && (
        <CredentialBanner email={credential.email} tempPassword={credential.tempPassword} onDismiss={() => setCredential(null)} />
      )}

      <form onSubmit={handleCreate} className="flex flex-wrap gap-3 items-end rounded-xl border border-slate-200 p-4">
        {isSuperAdmin && (
          <div>
            <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
              Organization <span className="text-red-500">*</span>
            </label>
            <select value={orgId} onChange={(e) => setOrgId(e.target.value ? Number(e.target.value) : "")}
                    className="rounded-lg border border-slate-200 px-3 py-2 text-sm bg-white">
              <option value="">All organizations</option>
              {orgs.filter((o) => !o.archived_at).map((o) => (
                <option key={o.id} value={o.id}>{o.name}</option>
              ))}
            </select>
          </div>
        )}
        <div>
          <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
            Email <span className="text-red-500">*</span>
          </label>
          <input value={email} onChange={(e) => setEmail(e.target.value)}
                 className="rounded-lg border border-slate-200 px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
            Name <span className="text-red-500">*</span>
          </label>
          <input value={displayName} onChange={(e) => setDisplayName(e.target.value)}
                 className="rounded-lg border border-slate-200 px-3 py-2 text-sm" />
        </div>
        {isSuperAdmin && (
          <div>
            <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Role</label>
            <div className="flex items-center gap-3 h-[38px]">
              <label className="flex items-center gap-1.5 text-sm text-slate-700 cursor-pointer">
                <input type="radio" name="new-user-role" checked={role === "analyser"}
                       onChange={() => setRole("analyser")} className="accent-[#5B2C9D]" />
                Analyser
              </label>
              <label className="flex items-center gap-1.5 text-sm text-slate-700 cursor-pointer">
                <input type="radio" name="new-user-role" checked={role === "admin"}
                       onChange={() => setRole("admin")} className="accent-[#5B2C9D]" />
                Admin
              </label>
              <label className="flex items-center gap-1.5 text-sm text-slate-700 cursor-pointer">
                <input type="radio" name="new-user-role" checked={role === "super_admin"}
                       onChange={() => setRole("super_admin")} className="accent-[#5B2C9D]" />
                Super Admin
              </label>
            </div>
          </div>
        )}
        <button type="submit" disabled={createDisabled}
                title={createDisabled ? "Fill in all required fields first" : undefined}
                className="rounded-lg bg-[#5B2C9D] text-white font-semibold px-4 py-2 text-sm disabled:opacity-40 disabled:cursor-not-allowed">
          {creating ? "Adding..." : isSuperAdmin ? `Add ${role === "super_admin" ? "Super Admin" : role === "admin" ? "Admin" : "Analyser"}` : "Add Analyser"}
        </button>
        <span className="text-xs text-slate-400 pb-2.5">A temp password is generated automatically.</span>
      </form>
      {error && <div className="text-sm text-red-600">{error}</div>}

      <div className="rounded-xl border border-slate-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 border-b border-slate-200">
            <tr className="text-left text-xs font-semibold text-slate-500 uppercase tracking-wide">
              <th className="px-4 py-2.5">Name</th>
              <th className="px-4 py-2.5">Email</th>
              <th className="px-4 py-2.5">Role</th>
              <th className="px-4 py-2.5">Created</th>
              <th className="px-4 py-2.5">Status</th>
              <th className="px-4 py-2.5"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {users.map((u) => (
              <tr key={u.id} className="hover:bg-slate-50/70">
                <td className="px-4 py-2.5 font-medium text-slate-800">{u.display_name}</td>
                <td className="px-4 py-2.5 text-slate-600">{u.email}</td>
                <td className="px-4 py-2.5 capitalize text-slate-600">{u.role}</td>
                <td className="px-4 py-2.5 text-slate-500 tabular-nums">
                  {u.created_at ? formatRelativeOrDate(u.created_at) : "—"}
                </td>
                <td className="px-4 py-2.5">
                  <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${u.archived_at ? "bg-slate-100 text-slate-500" : "bg-emerald-50 text-emerald-700"}`}>
                    {u.archived_at ? "Archived" : "Active"}
                  </span>
                </td>
                <td className="px-4 py-2.5 whitespace-nowrap">
                  <div className="flex items-center gap-3">
                    {!u.archived_at && (isSuperAdmin || u.role === "analyser") && (
                      <button onClick={() => handleResetPassword(u)} disabled={resettingId === u.id}
                              className="text-xs font-medium text-[#5B2C9D] hover:underline disabled:opacity-40">
                        {resettingId === u.id ? "Resetting..." : "Reset Password"}
                      </button>
                    )}
                    {!u.archived_at && u.role !== "admin" && (isSuperAdmin || u.role === "analyser") && (
                      <button onClick={() => intelApi.archiveUser(u.id).then(load)}
                              className="text-xs font-medium text-red-600 hover:underline">Archive</button>
                    )}
                    {isSuperAdmin && u.id !== currentUser?.id && (
                      <button
                        onClick={() => {
                          if (window.confirm(`Permanently delete ${u.display_name} (${u.email})? This cannot be undone.`)) {
                            intelApi.deleteUser(u.id).then(load);
                          }
                        }}
                        className="text-xs font-medium text-red-700 hover:underline"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
