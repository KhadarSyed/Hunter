import { useState } from "react";
import { intelApi, type OrgDetail } from "../../services/intel-api";
import { BrandLogo } from "../BrandLogo";
import { ProjectProgress } from "../ProjectProgress";
import { TabPanel, Tabs } from "../deliverable/Tabs";
import { CountryFlag, Meter, OrgLogo, Tile, fmtDate, fmtTokens, inputCls } from "./adminUi";

const NAME_MAX = 15;
const shortName = (name: string) => (name.length > NAME_MAX ? `${name.slice(0, NAME_MAX).trimEnd()}…` : name);

type Props = { detail: OrgDetail; canEditTokens: boolean; onChanged?: () => void };

/** One organization: plan tiles, projects (owner, stage, last updated, tokens) and users (tokens vs allowance).
 * Read-only for the Super Admin; the Org Admin can set each user's monthly token allowance. */
export function OrgDetailView({ detail, canEditTokens, onChanged }: Props) {
  const { org, subscription: s } = detail;
  const cur = s.current;
  const [tab, setTab] = useState<"projects" | "users">("projects");
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <OrgLogo name={org.name} logo={org.logo_url} variant="wide" />
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

      <Tabs label="Organization lists" active={tab} onChange={setTab} tabs={[
        { id: "projects", label: `Projects (${detail.projects.length})`, icon: "lucide:folder-kanban" },
        { id: "users", label: `Users (${detail.users.length})`, icon: "lucide:users" },
      ]} />

      {tab === "projects" && <TabPanel id="projects">
        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              <tr><th className="px-4 py-2">Project</th><th className="px-4 py-2">Owner</th><th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Created</th><th className="px-4 py-2">Last updated</th><th className="px-4 py-2 text-right">Tokens</th></tr>
            </thead>
            <tbody>
              {detail.projects.map((p) => (
                <tr key={p.id} className="border-t border-slate-100">
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-2.5" title={p.brand ? `${p.project_name} · ${p.brand}` : p.project_name}>
                      <BrandLogo brandName={p.brand || p.project_name} projectId={p.id} size={28} rounded="lg" />
                      <span className="min-w-0">
                        <span className="block font-medium text-slate-800 whitespace-nowrap">{shortName(p.project_name)}</span>
                        {p.brand && <span className="block text-xs text-slate-400 whitespace-nowrap">{shortName(p.brand)}</span>}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-2.5 text-slate-600">{p.owner_name ?? "—"}</td>
                  <td className="px-4 py-2.5"><ProjectProgress pct={p.progress_pct} stage={p.current_stage ?? undefined} size={30} /></td>
                  <td className="px-4 py-2.5 text-slate-600">{fmtDate(p.created_at)}</td>
                  <td className="px-4 py-2.5 text-slate-600">{fmtDate(p.updated_at)}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-slate-600">{fmtTokens(p.tokens)}</td>
                </tr>
              ))}
              {!detail.projects.length && <tr><td colSpan={6} className="px-4 py-6 text-center text-slate-400">No projects yet</td></tr>}
            </tbody>
          </table>
        </div>
      </TabPanel>}

      {tab === "users" && <TabPanel id="users">
        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              <tr><th className="px-4 py-2">User</th><th className="px-4 py-2">Role</th><th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Created</th><th className="px-4 py-2">Last sign-in</th>
                <th className="px-4 py-2 text-right">Tokens this month</th><th className="px-4 py-2">Monthly allowance</th></tr>
            </thead>
            <tbody>
              {detail.users.map((u) => (
                <tr key={u.id} className={`border-t border-slate-100 ${u.archived_at ? "bg-slate-50/60" : ""}`}>
                  <td className="px-4 py-2.5"><div className="font-medium text-slate-800">{u.display_name}</div><div className="text-xs text-slate-400">{u.email}</div></td>
                  <td className="px-4 py-2.5 capitalize text-slate-600">{u.role}</td>
                  <td className="px-4 py-2.5"><UserStatus active={!u.archived_at} /></td>
                  <td className="px-4 py-2.5 text-slate-600">{fmtDate(u.created_at)}</td>
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
      </TabPanel>}
    </div>
  );
}

function UserStatus({ active }: { active: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${active ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${active ? "bg-emerald-500" : "bg-slate-400"}`} aria-hidden />
      {active ? "Active" : "Inactive"}
    </span>
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
