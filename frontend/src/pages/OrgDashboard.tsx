import { useCallback, useEffect, useState } from "react";
import { useAuth } from "../context/auth-context";
import { intelApi, type OrgDetail } from "../services/intel-api";
import { OrgDetailView } from "../components/admin/OrgDetailView";
import { ghostBtn } from "../components/admin/adminUi";

type Props = { onNavigate: (page: string) => void };

/** Org Admin landing page: the organization's plan, its projects (owner, stage, last updated) and each user's token
 * use against the monthly allowance the Admin sets here. */
export function OrgDashboard({ onNavigate }: Props) {
  const { user } = useAuth();
  const [detail, setDetail] = useState<OrgDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const orgId = user?.org_id;

  const load = useCallback(() => {
    if (!orgId) return;
    intelApi.orgDetail(orgId).then(setDetail).catch((e) => setError(e instanceof Error ? e.message : "Could not load"));
  }, [orgId]);
  useEffect(() => { load(); }, [load]);

  if (user?.role !== "admin") return <div className="p-8 text-sm text-slate-500">This dashboard is for organization Admins.</div>;
  if (error) return <div className="p-8 text-sm text-red-600">{error}</div>;
  if (!detail) return <div className="p-8 text-sm text-slate-500">Loading dashboard…</div>;

  return (
    <div className="max-w-6xl mx-auto p-8 space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Organization dashboard</h1>
          <p className="text-sm text-slate-500">Projects, owners, last updates and token use. Set a user's monthly allowance in the Users table.</p>
        </div>
        <div className="flex gap-2">
          <button className={ghostBtn} onClick={() => onNavigate("settings")}>Users &amp; settings</button>
          <button className={ghostBtn} onClick={() => onNavigate("projects")}>Open projects</button>
        </div>
      </header>
      <OrgDetailView detail={detail} canEditTokens onChanged={load} />
    </div>
  );
}
