import { useEffect, useMemo, useState } from "react";
import { Icon } from "@iconify/react";
import { intelApi, type Plan } from "../../services/intel-api";
import { CredentialBanner } from "../../pages/ManageUsersTab";
import { ghostBtn, inputCls, labelCls, primaryBtn } from "./adminUi";

// ISO 3166-1 alpha-2; names come from the browser (Intl.DisplayNames)
const COUNTRY_CODES = ("ad ae af ag ai al am ao ar at au aw az ba bb bd be bf bg bh bi bj bm bn bo br bs bt bw by bz ca cd cf "
  + "cg ch ci cl cm cn co cr cu cv cy cz de dj dk dm do dz ec ee eg er es et fi fj fm fr ga gb gd ge gh gi gm gn gq gr gt gw gy "
  + "hk hn hr ht hu id ie il in iq ir is it jm jo jp ke kg kh km kn kp kr kw ky kz la lb lc li lk lr ls lt lu lv ly ma mc md me mg "
  + "mk ml mm mn mo mr mt mu mv mw mx my mz na ne ng ni nl no np nz om pa pe pg ph pk pl pr ps pt pw py qa ro rs ru rw sa sb sc sd "
  + "se sg si sk sl sm sn so sr ss st sv sy sz td tg th tj tl tm tn to tr tt tw tz ua ug us uy uz va vc ve vn vu ws ye za zm zw").split(" ");
const MAX_LOGO_BYTES = 1024 * 1024;

type Props = { onCreated: () => void; onCancel: () => void };

/** Super Admin: a new organization. The procurement manager's email becomes the org's Admin (welcome email with a
 * one-time password); the chosen plan starts today. */
export function NewOrgForm({ onCreated, onCancel }: Props) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [f, setF] = useState({ name: "", procName: "", procEmail: "", phone: "", address: "", country: "in", pin: "", planId: 0 });
  const [logo, setLogo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [credential, setCredential] = useState<{ email: string; tempPassword: string } | null>(null);
  const countries = useMemo(() => {
    const names = new Intl.DisplayNames(undefined, { type: "region" });
    return COUNTRY_CODES.map((c) => ({ code: c, name: names.of(c.toUpperCase()) ?? c.toUpperCase() }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, []);

  useEffect(() => {
    intelApi.listPlans().then((p) => { setPlans(p); setF((s) => ({ ...s, planId: s.planId || p[0]?.id || 0 })); })
      .catch(() => setError("Could not load plans"));
  }, []);

  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setF((s) => ({ ...s, [k]: k === "planId" ? Number(e.target.value) : e.target.value }));

  const pickLogo = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/")) { setError("The logo must be an image"); return; }
    if (file.size > MAX_LOGO_BYTES) { setError("The logo must be 1 MB or smaller"); return; }
    const reader = new FileReader();
    reader.onload = () => { setLogo(String(reader.result)); setError(null); };
    reader.readAsDataURL(file);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const created = await intelApi.createOrganization(f.name.trim(), f.procEmail.trim(), f.procName.trim(), {
        logo_url: logo, procurement_phone: f.phone.trim(), address: f.address.trim(), country: f.country,
        pin_code: f.pin.trim(), plan_id: f.planId || undefined,
      });
      if (created.temp_password) setCredential({ email: f.procEmail.trim(), tempPassword: created.temp_password });
      else onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create organization");
    } finally {
      setBusy(false);
    }
  };

  if (credential) {
    return (
      <div className="space-y-4">
        <CredentialBanner email={credential.email} tempPassword={credential.tempPassword} onDismiss={onCreated} />
        <button className={primaryBtn} onClick={onCreated}>Done</button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="flex items-center gap-4">
        <label className="h-16 w-16 shrink-0 cursor-pointer rounded-xl border border-dashed border-slate-300 bg-slate-50 flex items-center justify-center overflow-hidden hover:border-[#5B2C9D]">
          {logo ? <img src={logo} alt="Logo preview" className="h-full w-full object-contain" />
            : <span className="text-[11px] text-slate-400 text-center leading-tight">Upload<br />logo</span>}
          <input type="file" accept="image/*" className="sr-only" onChange={pickLogo} />
        </label>
        <div className="flex-1">
          <label className={labelCls}>Organization name</label>
          <input value={f.name} onChange={set("name")} required className={inputCls} />
        </div>
      </div>
      <fieldset className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <legend className="text-sm font-semibold text-slate-800 mb-2">Procurement manager <span className="font-normal text-slate-500">— becomes the organization's Admin</span></legend>
        <div><label className={labelCls}>Name</label><input value={f.procName} onChange={set("procName")} required className={inputCls} /></div>
        <div><label className={labelCls}>Email</label><input type="email" value={f.procEmail} onChange={set("procEmail")} required className={inputCls} /></div>
        <div><label className={labelCls}>Phone</label><input type="tel" value={f.phone} onChange={set("phone")} required className={inputCls} /></div>
      </fieldset>
      <div><label className={labelCls}>Address</label><textarea value={f.address} onChange={set("address")} required rows={2} className={inputCls} /></div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="sm:col-span-2">
          <label className={labelCls}>Country</label>
          <div className="relative">
            <Icon icon={`circle-flags:${f.country}`} width={18} className="absolute left-2.5 top-1/2 -translate-y-1/2" aria-hidden="true" />
            <select value={f.country} onChange={set("country")} className={`${inputCls} pl-9`}>
              {countries.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
            </select>
          </div>
        </div>
        <div><label className={labelCls}>PIN / postal code</label><input value={f.pin} onChange={set("pin")} required className={inputCls} /></div>
      </div>
      <div>
        <label className={labelCls}>Subscription plan (starts today)</label>
        <select value={f.planId} onChange={set("planId")} className={inputCls}>
          {plans.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} — {p.max_users} users, {p.max_projects} projects, {p.duration_months} months
            </option>
          ))}
        </select>
      </div>
      {error && <div className="text-sm text-red-600" role="alert">{error}</div>}
      <div className="flex justify-end gap-2 pt-2">
        <button type="button" className={ghostBtn} onClick={onCancel}>Cancel</button>
        <button type="submit" className={primaryBtn} disabled={busy}>{busy ? "Creating…" : "Create organization"}</button>
      </div>
    </form>
  );
}
