import { useState } from "react";
import { intelApi } from "../services/intel-api";
import { useAuth } from "../context/auth-context";
import { PasswordRules, passwordMeetsPolicy } from "../components/PasswordRules";

export function ChangePasswordPage() {
  const { user, refreshMe } = useAuth();
  const email = user?.email ?? "";
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const canSubmit = !!currentPassword && passwordMeetsPolicy(newPassword, email) && newPassword === confirm && !submitting;

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
    <div className="flex items-center justify-center min-h-screen bg-slate-50 px-4">
      <form onSubmit={handleSubmit} className="w-full max-w-sm bg-white rounded-xl border border-slate-200 p-8 shadow-sm">
        <h1 className="text-xl font-bold text-slate-900 mb-2">Set a new password</h1>
        <p className="text-sm text-slate-500 mb-6">You're using a temporary password — set your own before continuing.</p>
        {error && <div className="mb-4 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2" role="alert">{error}</div>}
        <label htmlFor="cp-current" className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Temporary password</label>
        <input id="cp-current" type="password" autoComplete="current-password" value={currentPassword}
               onChange={(e) => setCurrentPassword(e.target.value)} required
               className="w-full mb-4 rounded-lg border border-slate-200 px-3 py-2 text-sm" />
        <label htmlFor="cp-new" className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">New password</label>
        <input id="cp-new" type="password" autoComplete="new-password" value={newPassword}
               onChange={(e) => setNewPassword(e.target.value)} required
               className="w-full mb-3 rounded-lg border border-slate-200 px-3 py-2 text-sm" />
        <PasswordRules password={newPassword} email={email} />
        <label htmlFor="cp-confirm" className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Confirm new password</label>
        <input id="cp-confirm" type="password" autoComplete="new-password" value={confirm}
               onChange={(e) => setConfirm(e.target.value)} required
               className="w-full mb-1 rounded-lg border border-slate-200 px-3 py-2 text-sm" />
        <p className="mb-5 min-h-[1rem] text-xs text-red-600">{confirm && confirm !== newPassword ? "The passwords do not match" : ""}</p>
        <button type="submit" disabled={!canSubmit}
                className="w-full rounded-lg bg-[#5B2C9D] text-white font-semibold py-2 text-sm disabled:opacity-50">
          {submitting ? "Saving..." : "Set password"}
        </button>
      </form>
    </div>
  );
}
