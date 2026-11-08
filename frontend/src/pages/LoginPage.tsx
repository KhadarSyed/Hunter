import { useState } from "react";
import { useAuth } from "../context/auth-context";
import { intelApi } from "../services/intel-api";

type Mode = "login" | "email" | "code" | "sent";
const label = "block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1";
const input = "w-full rounded-lg border border-slate-200 px-3 py-2 text-sm";
const primary = "w-full rounded-lg bg-[#5B2C9D] text-white font-semibold py-2 text-sm disabled:opacity-50";
const link = "text-xs font-medium text-[#5B2C9D] hover:underline";

/** Sign in, plus Forgot password: email → 6-digit code → a one-time reset link is emailed (see auth/recovery.py). */
export function LoginPage() {
  const { login } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const run = async (fn: () => Promise<void>) => {
    setError(null);
    setSubmitting(true);
    try { await fn(); } catch (err) { setError(err instanceof Error ? err.message : "Something went wrong"); }
    finally { setSubmitting(false); }
  };
  const go = (next: Mode) => { setMode(next); setError(null); setNote(null); };

  const handleLogin = (e: React.FormEvent) => { e.preventDefault(); run(() => login(email, password)); };
  const handleSendCode = (e: React.FormEvent) => {
    e.preventDefault();
    run(async () => {
      const r = await intelApi.forgotPassword(email);
      setCode(""); setNote(r.message); setMode("code");
    });
  };
  const handleVerify = (e: React.FormEvent) => {
    e.preventDefault();
    run(async () => {
      const r = await intelApi.verifyResetCode(email, code);
      setNote(r.message); setMode("sent");
    });
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-slate-50 px-4">
      <div className="w-full max-w-sm bg-white rounded-xl border border-slate-200 p-8 shadow-sm">
        <h1 className="text-xl font-bold text-slate-900 mb-6">{mode === "login" ? "Sign in" : "Reset your password"}</h1>
        {error && <div className="mb-4 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2" role="alert">{error}</div>}
        {note && <div className="mb-4 text-sm text-emerald-800 bg-emerald-50 rounded-lg px-3 py-2" role="status">{note}</div>}

        {mode === "login" && (
          <form onSubmit={handleLogin}>
            <label htmlFor="li-email" className={label}>Email</label>
            <input id="li-email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)}
                   required className={`${input} mb-4`} />
            <div className="flex items-baseline justify-between">
              <label htmlFor="li-pw" className={label}>Password</label>
              <button type="button" onClick={() => go("email")} className={link}>Forgot password?</button>
            </div>
            <input id="li-pw" type="password" autoComplete="current-password" value={password}
                   onChange={(e) => setPassword(e.target.value)} required className={`${input} mb-6`} />
            <button type="submit" disabled={submitting} className={primary}>{submitting ? "Signing in..." : "Sign in"}</button>
          </form>
        )}

        {mode === "email" && (
          <form onSubmit={handleSendCode}>
            <p className="mb-4 text-sm text-slate-500">Enter your registered email. We will send a 6-digit code to confirm it.</p>
            <label htmlFor="fp-email" className={label}>Email</label>
            <input id="fp-email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)}
                   required className={`${input} mb-6`} />
            <button type="submit" disabled={submitting} className={primary}>{submitting ? "Sending..." : "Send code"}</button>
            <button type="button" onClick={() => go("login")} className={`${link} mt-4 block`}>Back to sign in</button>
          </form>
        )}

        {mode === "code" && (
          <form onSubmit={handleVerify}>
            <label htmlFor="fp-code" className={label}>6-digit code sent to {email}</label>
            <input id="fp-code" inputMode="numeric" autoComplete="one-time-code" pattern="\d{6}" maxLength={6}
                   value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} required
                   className={`${input} mb-6 text-center text-lg tracking-[0.5em]`} />
            <button type="submit" disabled={submitting || code.length !== 6} className={primary}>
              {submitting ? "Checking..." : "Confirm code"}
            </button>
            <div className="mt-4 flex justify-between">
              <button type="button" onClick={() => go("email")} className={link}>Send a new code</button>
              <button type="button" onClick={() => go("login")} className={link}>Back to sign in</button>
            </div>
          </form>
        )}

        {mode === "sent" && (
          <>
            <p className="mb-6 text-sm text-slate-600">Open the link in the email to choose a new password. It works once and expires in 30 minutes.</p>
            <button type="button" onClick={() => go("login")} className={primary}>Back to sign in</button>
          </>
        )}
      </div>
    </div>
  );
}
