import { useState } from "react";
import { intelApi } from "../services/intel-api";
import { useAuth } from "../context/auth-context";

export function ChangePasswordPage() {
  const { refreshMe } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await intelApi.changePassword(currentPassword, newPassword);
      await refreshMe();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to change password");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-slate-50">
      <form onSubmit={handleSubmit} className="w-full max-w-sm bg-white rounded-xl border border-slate-200 p-8 shadow-sm">
        <h1 className="text-xl font-bold text-slate-900 mb-2">Set a new password</h1>
        <p className="text-sm text-slate-500 mb-6">You're using a temporary password — set your own before continuing.</p>
        {error && <div className="mb-4 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</div>}
        <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Temporary password</label>
        <input type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} required
               className="w-full mb-4 rounded-lg border border-slate-200 px-3 py-2 text-sm" />
        <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">New password (min 8 characters)</label>
        <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required minLength={8}
               className="w-full mb-6 rounded-lg border border-slate-200 px-3 py-2 text-sm" />
        <button type="submit" disabled={submitting}
                className="w-full rounded-lg bg-[#5B2C9D] text-white font-semibold py-2 text-sm disabled:opacity-50">
          {submitting ? "Saving..." : "Set password"}
        </button>
      </form>
    </div>
  );
}
