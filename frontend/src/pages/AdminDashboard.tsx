import { useCallback, useEffect, useState } from "react";
import { intelApi, type AdminOverview, type OrgDetail, type Plan, type PlanInput } from "../services/intel-api";
import { ManageUsersTab } from "./ManageUsersTab";
import { NewOrgForm } from "../components/admin/NewOrgForm";
import { OrgDetailView } from "../components/admin/OrgDetailView";
import {
  CountryFlag, Meter, Modal, OrgLogo, Tile, fmtDate, fmtTokens, ghostBtn, inputCls, labelCls, primaryBtn,
} from "../components/admin/adminUi";

type Dialog = "org" | "user" | "plans" | null;

/** Super Admin landing page: every organization's plan, seats, projects and token use, read-only (projects are
 * reviewed here, never opened). New organizations, users and plans are created, and plans applied, from here. */
export function AdminDashboard() {
  const [data, setData] = useState<AdminOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [detail, setDetail] = useState<OrgDetail | null>(null);
  const [query, setQuery] = useState("");

  const load = useCallback(() => {
    intelApi.adminOverview().then(setData).catch((e) => setError(e instanceof Error ? e.message : "Could not load"));
  }, []);
  useEffect(() => { load(); }, [load]);

  const openOrg = (id: number) => intelApi.orgDetail(id).then(setDetail).catch(() => setError("Could not open that organization"));
  const close = () => { setDialog(null); load(); };

  if (error && !data) return <div className="p-8 text-sm text-red-600">{error}</div>;
  if (!data) return <div className="p-8 text-sm text-slate-500">Loading dashboard…</div>;
  const c = data.counts;
  const orgs = data.orgs.filter((o) => o.name.toLowerCase().includes(query.trim().toLowerCase()));

  return (
    <div className="max-w-7xl mx-auto p-8 space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Platform dashboard</h1>
          <p className="text-sm text-slate-500">Organizations, subscriptions, users, projects and token use. Projects are review-only here.</p>
        </div>
        <div className="flex gap-2">
          <button className={ghostBtn} onClick={() => setDialog("plans")}>Plans</button>
          <button className={ghostBtn} onClick={() => setDialog("user")}>New user</button>
          <button className={primaryBtn} onClick={() => setDialog("org")}>New organization</button>
        </div>
      </header>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Tile label="Organizations" value={c.orgs} />
        <Tile label="Users" value={c.users} />
        <Tile label="Projects" value={c.projects} />
        <Tile label="Active subscriptions" value={c.active_subscriptions} sub={`${c.orgs - c.active_subscriptions} without a plan`}
              tone={c.orgs > c.active_subscriptions ? "bad" : "default"} />
        <Tile label="Expiring in 30 days" value={c.expiring_30d} tone={c.expiring_30d ? "warn" : "default"} sub="no renewal queued" />
      </div>

      <section className="rounded-xl border border-slate-200 bg-white">
        <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-900">Organizations</h2>
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search organizations"
                 aria-label="Search organizations" className={`${inputCls} max-w-xs py-1.5`} />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2">Organization</th><th className="px-4 py-2">Country</th><th className="px-4 py-2">Plan</th>
                <th className="px-4 py-2">Expires</th><th className="px-4 py-2">Users</th><th className="px-4 py-2">Projects</th>
                <th className="px-4 py-2 text-right">Tokens (month)</th>
              </tr>
            </thead>
            <tbody>
              {orgs.map((o) => {
                const expiring = o.plan && o.days_left <= 30 && !o.renewal_queued;
                return (
                  <tr key={o.id} onClick={() => openOrg(o.id)} tabIndex={0}
                      onKeyDown={(e) => { if (e.key === "Enter") openOrg(o.id); }}
                      className={`border-t border-slate-100 cursor-pointer hover:bg-[#5B2C9D08] focus:bg-[#5B2C9D08] focus:outline-none ${o.archived_at ? "opacity-50" : ""}`}>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2.5">
                        <OrgLogo name={o.name} logo={o.logo_url} />
                        <div><div className="font-medium text-slate-800">{o.name}</div>
                          <div className="text-xs text-slate-400">{o.procurement_email ?? "—"}{o.archived_at ? " · archived" : ""}</div></div>
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-slate-600"><CountryFlag code={o.country} /></td>
                    <td className="px-4 py-2.5">
                      {o.plan ? <span className="rounded-full bg-[#5B2C9D10] px-2 py-0.5 text-xs font-medium text-[#5B2C9D]">{o.plan}</span>
                        : <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700">Expired</span>}
                      {o.renewal_queued && <span className="ml-1.5 text-[11px] text-emerald-700">renewal queued</span>}
                    </td>
                    <td className={`px-4 py-2.5 ${expiring ? "text-amber-700 font-medium" : "text-slate-600"}`}>
                      {fmtDate(o.ends_at)}{o.plan && <span className="block text-[11px] text-slate-400">{o.days_left} days</span>}
                    </td>
                    <td className="px-4 py-2.5"><Meter used={o.users} max={o.max_users} /></td>
                    <td className="px-4 py-2.5"><Meter used={o.projects} max={o.max_projects} /></td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-slate-600">{fmtTokens(o.tokens_month)}</td>
                  </tr>
                );
              })}
              {!orgs.length && <tr><td colSpan={7} className="px-4 py-8 text-center text-slate-400">No organizations match</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      {detail && (
        <Modal title="Organization" onClose={() => { setDetail(null); load(); }} wide>
          <div className="space-y-6">
            <ApplyPlan orgId={detail.org.id} onApplied={() => openOrg(detail.org.id)} />
            <OrgDetailView detail={detail} canEditTokens={false} />
          </div>
        </Modal>
      )}
      {dialog === "org" && <Modal title="New organization" onClose={close} wide><NewOrgForm onCreated={close} onCancel={close} /></Modal>}
      {dialog === "user" && <Modal title="Users" onClose={close} wide><ManageUsersTab /></Modal>}
      {dialog === "plans" && <Modal title="Subscription plans" onClose={close} wide><PlansEditor /></Modal>}
    </div>
  );
}

/** Super Admin applies a plan to one organization: new, renewal, upgrade or top-up. There is no payment in the app;
 * a plan applied while one is running is queued to start when it ends. The org's admins are emailed. */
function ApplyPlan({ orgId, onApplied }: { orgId: number; onApplied: () => void }) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [planId, setPlanId] = useState(0);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => {
    intelApi.listPlans().then((p) => { setPlans(p); setPlanId(p[0]?.id ?? 0); })
      .catch(() => setMsg({ ok: false, text: "Could not load plans" }));
  }, []);

  const apply = async () => {
    if (!planId) return;
    setBusy(true); setMsg(null);
    try {
      const sub = await intelApi.grantPlan(orgId, planId);
      setMsg({ ok: true, text: sub.status === "queued"
        ? `${sub.plan_name} queued: starts ${fmtDate(sub.starts_at)}, when the current plan ends.`
        : `${sub.plan_name} active until ${fmtDate(sub.ends_at)}.` });
      onApplied();
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Could not apply the plan" }); }
    finally { setBusy(false); }
  };

  return (
    <section className="rounded-xl border border-slate-200 p-4">
      <label className={labelCls} htmlFor="apply-plan">Apply a plan (new, renewal, upgrade or top-up)</label>
      <div className="flex flex-wrap items-center gap-2">
        <select id="apply-plan" value={planId} onChange={(e) => setPlanId(Number(e.target.value))} className={`${inputCls} max-w-sm`}>
          {plans.map((p) => (
            <option key={p.id} value={p.id}>{p.name}: {p.max_users} users · {p.max_projects} projects · {p.duration_months} months</option>
          ))}
        </select>
        <button className={primaryBtn} onClick={apply} disabled={busy || !planId}>{busy ? "Applying…" : "Apply plan"}</button>
      </div>
      {msg && <div role={msg.ok ? "status" : "alert"} className={`mt-2 text-sm ${msg.ok ? "text-emerald-700" : "text-red-600"}`}>{msg.text}</div>}
    </section>
  );
}

const EMPTY_PLAN: PlanInput = { name: "", max_users: 5, max_projects: 10, duration_months: 12, price: 0, currency: "USD", active: true };

function PlansEditor() {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [edit, setEdit] = useState<{ id?: number; plan: PlanInput } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => intelApi.listPlans(true).then(setPlans).catch(() => setError("Could not load plans"));
  useEffect(() => { load(); }, []);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!edit) return;
    try { await intelApi.savePlan(edit.plan, edit.id); setEdit(null); setError(null); load(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not save the plan"); }
  };
  const num = (k: keyof PlanInput) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setEdit((s) => (s ? { ...s, plan: { ...s.plan, [k]: Number(e.target.value) } } : s));

  return (
    <div className="space-y-4">
      <table className="w-full text-sm">
        <thead className="text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          <tr><th className="py-2">Plan</th><th>Users</th><th>Projects</th><th>Months</th><th>Price</th><th>Status</th><th /></tr>
        </thead>
        <tbody>
          {plans.map((p) => (
            <tr key={p.id} className="border-t border-slate-100">
              <td className="py-2 font-medium">{p.name}</td><td>{p.max_users}</td><td>{p.max_projects}</td><td>{p.duration_months}</td>
              <td>{p.price.toLocaleString()} {p.currency}</td><td>{p.active ? "Active" : "Hidden"}</td>
              <td className="text-right"><button className="text-xs text-[#5B2C9D] hover:underline"
                onClick={() => setEdit({ id: p.id, plan: { ...p, active: Boolean(p.active) } })}>Edit</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {!edit && <button className={ghostBtn} onClick={() => setEdit({ plan: EMPTY_PLAN })}>Add plan</button>}
      {edit && (
        <form onSubmit={save} className="grid grid-cols-2 sm:grid-cols-4 gap-3 rounded-xl border border-slate-200 p-4">
          <div className="col-span-2"><label className={labelCls}>Name</label>
            <input value={edit.plan.name} required className={inputCls}
                   onChange={(e) => setEdit({ ...edit, plan: { ...edit.plan, name: e.target.value } })} /></div>
          <div><label className={labelCls}>Users</label><input type="number" min={1} value={edit.plan.max_users} onChange={num("max_users")} className={inputCls} /></div>
          <div><label className={labelCls}>Projects</label><input type="number" min={1} value={edit.plan.max_projects} onChange={num("max_projects")} className={inputCls} /></div>
          <div><label className={labelCls}>Months</label><input type="number" min={1} max={60} value={edit.plan.duration_months} onChange={num("duration_months")} className={inputCls} /></div>
          <div><label className={labelCls}>Price</label><input type="number" min={0} step="0.01" value={edit.plan.price} onChange={num("price")} className={inputCls} /></div>
          <div><label className={labelCls}>Currency</label>
            <input value={edit.plan.currency} maxLength={3} className={inputCls}
                   onChange={(e) => setEdit({ ...edit, plan: { ...edit.plan, currency: e.target.value.toUpperCase() } })} /></div>
          <label className="flex items-end gap-2 pb-2 text-sm text-slate-700">
            <input type="checkbox" checked={edit.plan.active} onChange={(e) => setEdit({ ...edit, plan: { ...edit.plan, active: e.target.checked } })} />
            Offered to orgs
          </label>
          <div className="col-span-2 sm:col-span-4 flex justify-end gap-2">
            <button type="button" className={ghostBtn} onClick={() => setEdit(null)}>Cancel</button>
            <button type="submit" className={primaryBtn}>Save plan</button>
          </div>
        </form>
      )}
      {error && <div className="text-sm text-red-600" role="alert">{error}</div>}
    </div>
  );
}
