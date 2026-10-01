import { useEffect, useState } from "react";
import { intelApi, type AuthUserRow } from "../services/intel-api";

export function ManageUsersTab() {
  const [users, setUsers] = useState<AuthUserRow[]>([]);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [tempPassword, setTempPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = () => intelApi.listUsers().then(setUsers);
  useEffect(() => { load(); }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await intelApi.createUser(email, displayName, "analyser", tempPassword);
      setEmail(""); setDisplayName(""); setTempPassword("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create user");
    }
  };

  return (
    <div className="space-y-8">
      <form onSubmit={handleCreate} className="flex flex-wrap gap-2 items-end">
        <div>
          <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Email</label>
          <input value={email} onChange={(e) => setEmail(e.target.value)} required
                 className="rounded-lg border border-slate-200 px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Name</label>
          <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} required
                 className="rounded-lg border border-slate-200 px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Temp password</label>
          <input value={tempPassword} onChange={(e) => setTempPassword(e.target.value)} required minLength={8}
                 className="rounded-lg border border-slate-200 px-3 py-2 text-sm" />
        </div>
        <button type="submit" className="rounded-lg bg-[#5B2C9D] text-white font-semibold px-4 py-2 text-sm">
          Add Analyser
        </button>
      </form>
      {error && <div className="text-sm text-red-600">{error}</div>}
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs font-semibold text-slate-400 uppercase tracking-wide">
            <th className="py-2">Name</th><th>Email</th><th>Role</th><th>Status</th><th></th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className="border-t border-slate-100">
              <td className="py-2">{u.display_name}</td>
              <td>{u.email}</td>
              <td className="capitalize">{u.role}</td>
              <td>{u.archived_at ? "Archived" : "Active"}</td>
              <td>
                {!u.archived_at && u.role !== "admin" && (
                  <button onClick={() => intelApi.archiveUser(u.id).then(load)}
                          className="text-xs text-red-600">Archive</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
