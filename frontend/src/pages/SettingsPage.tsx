import { useState } from "react";
import { useAuth } from "../context/auth-context";
import { ProfileSettingsTab } from "./ProfileSettingsTab";
import { ManageUsersTab } from "./ManageUsersTab";
import { ManageOrganizationTab } from "./ManageOrganizationTab";
import { DataSourcesTab } from "./DataSourcesTab";
import { ExclusionsTab } from "./ExclusionsTab";
import { ProvidersTab } from "./ProvidersTab";
import { SubscriptionTab } from "./SubscriptionTab";
import { GuardrailsTab } from "./GuardrailsTab";
import { OrgLogo } from "../components/admin/adminUi";

type SettingsTab = "profile" | "users" | "organizations" | "datasources" | "exclusions" | "providers" | "subscription"
  | "guardrails";

const ROLE_LABELS: Record<string, string> = {
  super_admin: "Super Admin",
  admin: "Admin",
  analyser: "Analyser",
};

export function SettingsPage() {
  const { user } = useAuth();
  // An emailed link can open a tab directly: /settings?tab=providers.
  const [tab, setTab] = useState<SettingsTab>(
    () => (new URLSearchParams(window.location.search).get("tab") as SettingsTab | null) ?? "profile");
  if (!user) return null;

  const tabs: { id: SettingsTab; label: string }[] = [
    { id: "profile", label: "My Profile" },
    ...(user.role === "admin" || user.role === "analyser" || user.role === "super_admin"
      ? [{ id: "exclusions" as const, label: "Exclusions" }] : []),
    ...(user.role === "admin" || user.role === "super_admin"
      ? [{ id: "users" as const, label: "Organization Users" },
         { id: "datasources" as const, label: "Data Sources" },
         { id: "providers" as const, label: "LLM Providers" }] : []),
    ...(user.role === "admin" || user.role === "analyser"
      ? [{ id: "guardrails" as const, label: "Guardrails" }] : []),
    ...(user.role === "admin" ? [{ id: "subscription" as const, label: "Subscription" }] : []),
    ...(user.role === "super_admin"
      ? [{ id: "organizations" as const, label: "Manage Organization" }] : []),
  ];
  // a ?tab= this role does not have (an old link, a different role's tab) opens My Profile instead
  const current: SettingsTab = tabs.some((t) => t.id === tab) ? tab : "profile";

  return (
    <div className="max-w-5xl mx-auto p-8">
      <h1 className="text-xl font-bold text-slate-900 mb-6">Settings</h1>
      <div className="flex gap-6 items-start">
        <aside className="w-56 shrink-0 rounded-xl border border-slate-200 bg-white p-2">
          <div className="px-3 py-3 mb-1 border-b border-slate-100">
            {user.org_name && <div className="mb-2.5"><OrgLogo name={user.org_name} logo={user.org_logo_url} variant="wide" /></div>}
            <div className="text-sm font-semibold text-slate-900 truncate">{user.display_name}</div>
            <div className="text-xs text-slate-500 truncate">{user.email}</div>
            <div className="mt-1.5 flex items-center gap-1.5 flex-wrap">
              <span className="px-1.5 py-0.5 rounded bg-slate-100 text-[11px] font-medium text-slate-700">
                {ROLE_LABELS[user.role] ?? user.role}
              </span>
              {user.org_name && <span className="text-[11px] text-slate-500 truncate">{user.org_name}</span>}
            </div>
          </div>
          <nav className="py-1 space-y-0.5">
            {tabs.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                  current === t.id ? "bg-[#5B2C9D10] text-[#5B2C9D] font-medium" : "text-slate-600 hover:bg-slate-50"
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>
        </aside>
        <div className="flex-1 min-w-0 rounded-xl border border-slate-200 bg-white p-6">
          {current === "profile" && <ProfileSettingsTab />}
          {current === "users" && <ManageUsersTab />}
          {current === "datasources" && <DataSourcesTab />}
          {current === "exclusions" && <ExclusionsTab />}
          {current === "organizations" && <ManageOrganizationTab />}
          {current === "providers" && <ProvidersTab />}
          {current === "subscription" && <SubscriptionTab />}
          {current === "guardrails" && <GuardrailsTab />}
        </div>
      </div>
    </div>
  );
}
