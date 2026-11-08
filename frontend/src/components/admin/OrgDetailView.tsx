import { useState } from "react";
import { intelApi, type OrgDetail } from "../../services/intel-api";
import { CountryFlag, Meter, OrgLogo, STAGE_LABELS, Tile, fmtDate, fmtTokens, inputCls } from "./adminUi";

type Props = { detail: OrgDetail; canEditTokens: boolean; onChanged?: () => void };

/** One organization: plan tiles, projects (owner, stage, last updated, tokens) and users (tokens vs allowance).
 * Read-only for the Super Admin; the Org Admin can set each user's monthly token allowance. */
export function OrgDetailView({ detail, canEditTokens, onChanged }: Props) {
  const { org, subscription: s } = detail;
  const cur = s.current;
  return (
    <div className="space-y-6">
      <div className="flex items-start gap-3">
        <OrgLogo name={org.name} logo={org.logo_url} />
        <div className="min-w-0">
          <div className="text-lg font-semibold text-slate-900">{org.name}</div>
          <div className="text-xs text-slate-500 flex flex-wrap gap-x-3 gap-y-1">
            <CountryFlag code={org.country} />
            {org.procurement_name && <span>Procurement: {org.procurement_name} · {org.procurement_email}{org.procurement_phone ? ` · ${org.procurement_phone}` : ""}</span>}
            {org.address && <span>{org.address}{org.pin_code ? ` ${org.pin_code}` : ""}</span>}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Tile label="Plan" value={cur?.plan_name ?? "Expired"} tone={cur ? "default" : "bad"}
              sub={s.queued.length ? `Renewal queued: ${s.queued[0].plan_name}` : undefined} />
        <Tile label="Days left" value={cur ? s.days_left : 0} tone={!cur ? "bad" : s.days_left <= 30 && !s.queued.length ? "warn" : "default"}
              sub={cur ? `Ends ${fmtDate(cur.ends_at)}` : undefined} />
        <Tile label="Users" value={<Meter used={s.users} max={cur?.max_users ?? 0} />} />
        <Tile label="Projects" value={<Meter used={s.projects} max={cur?.max_projects ?? 0} />} />
      </div>

      <section>
        <h3 className="text-sm font-semibold text-slate-900 mb-2">Projects</h3>
        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              <tr><th className="px-4 py-2">Project</th><th className="px-4 py-2">Owner</th><th className="px-4 py-2">Stage</th>
                <th className="px-4 py-2">Last updated</th><th className="px-4 py-2 text-right">Tokens</th></tr>
            </thead>
            <tbody>
              {detail.projects.map((p) => (
                <tr key={p.id} className="border-t border-slate-100">
                  <td className="px-4 py-2.5 font-medium text-slate-800">{p.project_name}{p.brand && <span className="ml-1.5 text-xs text-slate-400">{p.brand}</span>}</td>
                  <td className="px-4 py-2.5 text-slate-600">{p.owner_name ?? "—"}</td>
                  <td className="px-4 py-2.5 text-slate-600">{STAGE_LABELS[p.current_stage ?? ""] ?? p.current_stage ?? "—"}</td>
                  <td className="px-4 py-2.5 text-slate-600">{fmtDate(p.updated_at)}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-slate-600">{fmtTokens(p.tokens)}</td>
                </tr>
              ))}
              {!detail.projects.length && <tr><td colSpan={5} className="px-4 py-6 text-center text-slate-400">No projects yet</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-semibold text-slate-900 mb-2">Users</h3>
        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              <tr><th className="px-4 py-2">User</th><th className="px-4 py-2">Role</th><th className="px-4 py-2">Last sign-in</th>
                <th className="px-4 py-2 text-right">Tokens this month</th><th className="px-4 py-2">Monthly allowance</th></tr>
            </thead>
            <tbody>
              {detail.users.map((u) => (
                <tr key={u.id} className={`border-t border-slate-100 ${u.archived_at ? "opacity-50" : ""}`}>
                  <td className="px-4 py-2.5"><div className="font-medium text-slate-800">{u.display_name}</div><div className="text-xs text-slate-400">{u.email}</div></td>
                  <td className="px-4 py-2.5 capitalize text-slate-600">{u.role}</td>
                  <td className="px-4 py-2.5 text-slate-600">{fmtDate(u.last_login)}</td>
                  <td className={`px-4 py-2.5 text-right tabular-nums ${u.monthly_tokens != null && u.tokens_month >= u.monthly_tokens ? "text-red-600 font-semibold" : "text-slate-600"}`}>
                    {fmtTokens(u.tokens_month)}
                  </td>
                  <td className="px-4 py-2.5">
                    {canEditTokens && !u.archived_at
                      ? <AllowanceInput userId={u.id} value={u.monthly_tokens} onSaved={onChanged} />
                      : <span className="text-slate-600">{u.monthly_tokens == null ? "Unlimited" : fmtTokens(u.monthly_tokens)}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function AllowanceInput({ userId, value, onSaved }: { userId: number; value: number | null; onSaved?: () => void }) {
  const [text, setText] = useState(value == null ? "" : String(value));
  const [state, setState] = useState<"idle" | "saving" | "error">("idle");
  const save = async () => {
    const trimmed = text.replace(/[,\s]/g, "");
    const next = trimmed === "" ? null : Number(trimmed);
    if (next !== null && (!Number.isInteger(next) || next < 0)) { setState("error"); return; }
    if (next === value) return;
    setState("saving");
    try { await intelApi.setTokenLimit(userId, next); setState("idle"); onSaved?.(); } catch { setState("error"); }
  };
  return (
    <input value={text} onChange={(e) => { setText(e.target.value); setState("idle"); }} onBlur={save}
           onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
           placeholder="Unlimited" inputMode="numeric" aria-label="Monthly token allowance"
           className={`${inputCls} max-w-[150px] py-1.5 ${state === "error" ? "border-red-400" : ""} ${state === "saving" ? "opacity-60" : ""}`} />
  );
}
