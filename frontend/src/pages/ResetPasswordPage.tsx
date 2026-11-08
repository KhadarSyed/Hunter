import { useState } from "react";
import { intelApi } from "../services/intel-api";
import { PasswordRules, passwordMeetsPolicy } from "../components/PasswordRules";

/** /reset-password?token=…: the page the emailed one-time link opens. Works signed in or out. */
export function ResetPasswordPage() {
  const token = new URLSearchParams(window.location.search).get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const canSubmit = passwordMeetsPolicy(password) && password === confirm && !submitting;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await intelApi.resetPassword(token, password);
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reset the password");
    } finally {
      setSubmitting(false);
    }
  };

  const goToSignIn = () => window.location.assign("/");
  const input = "w-full rounded-lg border border-slate-200 px-3 py-2 text-sm";
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="mb-2 text-xl font-bold text-slate-900">Choose a new password</h1>
        {!token ? (
          <>
            <p className="mb-6 text-sm text-red-600">This reset link is incomplete. Request a new one from the sign-in page.</p>
            <button type="button" onClick={goToSignIn} className="w-full rounded-lg bg-[#5B2C9D] py-2 text-sm font-semibold text-white">Back to sign in</button>
          </>
        ) : done ? (
          <>
            <p className="mb-6 text-sm text-slate-600" role="status">Your password has been changed and every other session was signed out. Sign in with your new password.</p>
            <button type="button" onClick={goToSignIn} className="w-full rounded-lg bg-[#5B2C9D] py-2 text-sm font-semibold text-white">Sign in</button>
          </>
        ) : (
          <form onSubmit={handleSubmit}>
            <p className="mb-6 text-sm text-slate-500">The link works once and expires 30 minutes after it was sent.</p>
            {error && <div className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600" role="alert">{error}</div>}
            <label htmlFor="rp-new" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">New password</label>
            <input id="rp-new" type="password" autoComplete="new-password" value={password}
                   onChange={(e) => setPassword(e.target.value)} required className={`${input} mb-3`} />
            <PasswordRules password={password} />
            <label htmlFor="rp-confirm" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Confirm new password</label>
            <input id="rp-confirm" type="password" autoComplete="new-password" value={confirm}
                   onChange={(e) => setConfirm(e.target.value)} required className={`${input} mb-1`} />
            <p className="mb-5 min-h-[1rem] text-xs text-red-600">{confirm && confirm !== password ? "The passwords do not match" : ""}</p>
            <button type="submit" disabled={!canSubmit}
                    className="w-full rounded-lg bg-[#5B2C9D] py-2 text-sm font-semibold text-white disabled:opacity-50">
              {submitting ? "Saving…" : "Set new password"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
