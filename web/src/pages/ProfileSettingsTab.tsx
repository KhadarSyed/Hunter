import { useState } from "react";
import { useAuth } from "../context/auth-context";
import { intelApi } from "../services/intel-api";

export function ProfileSettingsTab() {
  const { user, refreshMe } = useAuth();
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [saving, setSaving] = useState(false);
  if (!user) return null;

  const handleSave = async () => {
    setSaving(true);
    try {
      await intelApi.updateProfile(displayName);
      await refreshMe();
    } finally {
      setSaving(false);
    }
  };

  const handleAvatarChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await intelApi.uploadAvatar(file);
    await refreshMe();
  };

  return (
    <div className="space-y-6 max-w-md">
      <div className="flex items-center gap-4">
        {user.avatar_url && (
          <img src={user.avatar_url} alt="" className="w-16 h-16 rounded-full object-cover" />
        )}
        <label className="text-sm text-[#5B2C9D] font-medium cursor-pointer">
          Change photo
          <input type="file" accept="image/*" className="hidden" onChange={handleAvatarChange} />
        </label>
      </div>
      <div>
        <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Display name</label>
        <input value={displayName} onChange={(e) => setDisplayName(e.target.value)}
               className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" />
      </div>
      <div>
        <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Email</label>
        <div className="text-sm text-slate-700">{user.email}</div>
      </div>
      <div>
        <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Role</label>
        <div className="text-sm text-slate-700 capitalize">{user.role.replace("_", " ")}</div>
      </div>
      <button onClick={handleSave} disabled={saving}
              className="rounded-lg bg-[#5B2C9D] text-white font-semibold px-4 py-2 text-sm disabled:opacity-50">
        {saving ? "Saving..." : "Save"}
      </button>
    </div>
  );
}
