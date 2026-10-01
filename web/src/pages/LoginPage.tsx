import { useState } from "react";
import { useAuth } from "../context/auth-context";

export function LoginPage() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-slate-50">
      <form onSubmit={handleSubmit} className="w-full max-w-sm bg-white rounded-xl border border-slate-200 p-8 shadow-sm">
        <h1 className="text-xl font-bold text-slate-900 mb-6">Sign in</h1>
        {error && <div className="mb-4 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</div>}
        <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Email</label>
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required
               className="w-full mb-4 rounded-lg border border-slate-200 px-3 py-2 text-sm" />
        <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Password</label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
               className="w-full mb-6 rounded-lg border border-slate-200 px-3 py-2 text-sm" />
        <button type="submit" disabled={submitting}
                className="w-full rounded-lg bg-[#5B2C9D] text-white font-semibold py-2 text-sm disabled:opacity-50">
          {submitting ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </div>
  );
}
