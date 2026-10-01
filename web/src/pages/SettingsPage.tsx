import { useState } from "react";
import { useAuth } from "../context/auth-context";
import { ProfileSettingsTab } from "./ProfileSettingsTab";
import { ManageUsersTab } from "./ManageUsersTab";
import { ManageOrganizationTab } from "./ManageOrganizationTab";

type SettingsTab = "profile" | "users" | "organizations";

export function SettingsPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState<SettingsTab>("profile");
  if (!user) return null;

  const tabs: { id: SettingsTab; label: string }[] = [
    { id: "profile", label: "Profile" },
    ...(user.role === "admin" || user.role === "super_admin"
      ? [{ id: "users" as const, label: "Manage Users" }] : []),
    ...(user.role === "super_admin"
      ? [{ id: "organizations" as const, label: "Manage Organization" }] : []),
  ];

  return (
    <div className="max-w-4xl mx-auto p-8">
      <h1 className="text-xl font-bold text-slate-900 mb-6">Settings</h1>
      <div className="flex gap-1 border-b border-slate-200 mb-6">
        {tabs.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
                  className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
                    tab === t.id ? "border-[#5B2C9D] text-[#5B2C9D]" : "border-transparent text-slate-500"
                  }`}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === "profile" && <ProfileSettingsTab />}
      {tab === "users" && <ManageUsersTab />}
      {tab === "organizations" && <ManageOrganizationTab />}
    </div>
  );
}
