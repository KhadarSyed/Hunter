import { useCallback, useEffect, useState } from "react";
import { intelApi, type Plan, type SubscriptionSummary } from "../services/intel-api";
import { Meter, Tile, fmtDate } from "../components/admin/adminUi";

/** Settings → Subscription (Org Admin): current plan, queued renewal, the plans on offer and history. Read-only: there is
 * no payment in the app; the platform team (Super Admin) applies every plan, renewal and top-up. */
export function SubscriptionTab() {
  const [summary, setSummary] = useState<SubscriptionSummary | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    intelApi.subscription().then(setSummary).catch(() => setError("Could not load the subscription"));
    intelApi.listPlans().then(setPlans).catch(() => setError("Could not load plans"));
  }, []);
  useEffect(() => { load(); }, [load]);

  if (!summary) return <div className="text-sm text-slate-500">{error ?? "Loading…"}</div>;
  const cur = summary.current;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-base font-semibold text-slate-900">Subscription</h2>
        <p className="text-sm text-slate-500">Plans limit how many users and projects your organization can have. Your AI models are your own and are not part of the plan. To renew, upgrade or top up, contact the platform team: they apply it for you.</p>
      </div>
      {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">{error}</div>}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Tile label="Current plan" value={cur?.plan_name ?? "Expired"} tone={cur ? "default" : "bad"}
              sub={cur ? `${fmtDate(cur.starts_at)} – ${fmtDate(cur.ends_at)}` : "New users and projects are paused"} />
        <Tile label="Days left" value={summary.days_left} tone={!cur ? "bad" : summary.days_left <= 30 && !summary.queued.length ? "warn" : "default"} />
        <Tile label="Users" value={<Meter used={summary.users} max={cur?.max_users ?? 0} />} />
        <Tile label="Projects" value={<Meter used={summary.projects} max={cur?.max_projects ?? 0} />} />
      </div>
      {summary.queued.map((q) => (
        <div key={q.id} className="rounded-lg border border-[#5B2C9D30] bg-[#5B2C9D08] px-4 py-2.5 text-sm text-[#5B2C9D]">
          Renewal queued: <b>{q.plan_name}</b> from {fmtDate(q.starts_at)} to {fmtDate(q.ends_at)}.
        </div>
      ))}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {plans.map((p) => (
          <div key={p.id} className={`rounded-xl border p-4 flex flex-col ${cur?.plan_id === p.id ? "border-[#5B2C9D]" : "border-slate-200"}`}>
            <div className="flex items-center justify-between">
              <div className="font-semibold text-slate-900">{p.name}</div>
              {cur?.plan_id === p.id && <span className="text-[11px] font-medium text-[#5B2C9D]">Current</span>}
            </div>
            <div className="mt-1 text-2xl font-bold text-slate-900">{p.price.toLocaleString()} <span className="text-sm font-medium text-slate-500">{p.currency}</span></div>
            <ul className="mt-2 space-y-1 text-sm text-slate-600 flex-1">
              <li>{p.max_users} users</li><li>{p.max_projects} projects</li><li>{p.duration_months} months</li>
            </ul>
          </div>
        ))}
      </div>

      {summary.history.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold text-slate-900 mb-2">History</h3>
          <table className="w-full text-sm">
            <thead className="text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              <tr><th className="py-2">Plan</th><th>From</th><th>To</th><th>Status</th></tr>
            </thead>
            <tbody>
              {summary.history.map((h) => (
                <tr key={h.id} className="border-t border-slate-100">
                  <td className="py-2">{h.plan_name}</td><td>{fmtDate(h.starts_at)}</td><td>{fmtDate(h.ends_at)}</td>
                  <td className="capitalize">{h.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

    </div>
  );
}
