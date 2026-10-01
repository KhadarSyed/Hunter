import { useEffect, useState } from "react";
import { intelApi, type AuthOrganizationRow } from "../services/intel-api";

export function ManageOrganizationTab() {
  const [orgs, setOrgs] = useState<AuthOrganizationRow[]>([]);
  const [name, setName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [adminName, setAdminName] = useState("");
  const [adminTempPassword, setAdminTempPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = () => intelApi.listOrganizations().then(setOrgs);
  useEffect(() => { load(); }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await intelApi.createOrganization(name, adminEmail, adminName, adminTempPassword);
      setName(""); setAdminEmail(""); setAdminName(""); setAdminTempPassword("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create organization");
    }
  };

  return (
    <div className="space-y-8">
      <form onSubmit={handleCreate} className="flex flex-wrap gap-2 items-end">
        <div>
          <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Org name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} required
                 className="rounded-lg border border-slate-200 px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Admin name</label>
          <input value={adminName} onChange={(e) => setAdminName(e.target.value)} required
                 className="rounded-lg border border-slate-200 px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Admin email</label>
          <input value={adminEmail} onChange={(e) => setAdminEmail(e.target.value)} required
                 className="rounded-lg border border-slate-200 px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Temp password</label>
          <input value={adminTempPassword} onChange={(e) => setAdminTempPassword(e.target.value)} required minLength={8}
                 className="rounded-lg border border-slate-200 px-3 py-2 text-sm" />
        </div>
        <button type="submit" className="rounded-lg bg-[#5B2C9D] text-white font-semibold px-4 py-2 text-sm">
          Create Org
        </button>
      </form>
      {error && <div className="text-sm text-red-600">{error}</div>}
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs font-semibold text-slate-400 uppercase tracking-wide">
            <th className="py-2">Organization</th><th>Admin</th><th>Status</th><th></th>
          </tr>
        </thead>
        <tbody>
          {orgs.map((o) => (
            <tr key={o.id} className="border-t border-slate-100">
              <td className="py-2">{o.name}</td>
              <td>{o.admin_name} ({o.admin_email})</td>
              <td>{o.archived_at ? "Archived" : "Active"}</td>
              <td>
                {!o.archived_at && (
                  <button onClick={() => intelApi.archiveOrganization(o.id).then(load)}
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
