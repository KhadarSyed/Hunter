import { useEffect, useState } from "react";
import { useAuth } from "../context/auth-context";
import { intelApi } from "../services/intel-api";

type Mode = "login" | "email" | "code" | "sent";
const label = "block text-sm font-semibold text-white mb-2";
const input = "w-full rounded-xl border border-white/40 bg-white/90 px-4 py-3 text-[15px] text-slate-900 placeholder:text-slate-500 focus:border-white focus:bg-white focus:outline-none focus:ring-2 focus:ring-white/40";
const primary = "w-full rounded-xl bg-[#5B2C9D] py-3 text-[15px] font-semibold text-white shadow-lg shadow-black/30 hover:bg-[#6a36b3] disabled:opacity-50";
const link = "text-sm font-semibold text-violet-200 hover:text-white hover:underline";
// a signed link to the photo in S3 (backend auth/router.login_background); without one the page stays dark
const BACKGROUND = "/api/auth/login-background";
const SLIDE_MS = 6000;

// what the platform does, one slide each, shown over the photo
const SLIDES = [
  { tag: "Intelligent architecture", title: "From brief to boardroom deck",
    text: "Brief & Scope, background research, search strategy and tagging flow into one cited, branded deck." },
  { tag: "Background research", title: "Brand and competitor context in minutes",
    text: "News, brand and competitor signals from trusted sources, with your excluded websites and keywords left out." },
  { tag: "Search strategy", title: "A Boolean query for every research question",
    text: "Queries drafted from the brief, validated, and matched to your data set before a single article is tagged." },
  { tag: "AI tagging", title: "Every article read against your questions",
    text: "Sentiment, themes and relevance tagged by AI, reviewed by your analysts, and learned from their corrections." },
  { tag: "Evidence first", title: "Every number computed, every claim cited",
    text: "Figures come from the data, never from the model, and every insight links back to the articles behind it." },
  { tag: "Deliverables", title: "Decks, briefs and data in one run",
    text: "PowerPoint, PDF, Word and Excel in your brand, with a click-through to the articles behind every chart." },
  { tag: "Your models, your rules", title: "Bring your own AI, with guardrails",
    text: "Your organization's models with automatic failover, guardrails on every prompt, and cost tracked per project." },
];

/** The AlphaMetricx mark and the feature slider over the photo: wide screens only, beside the sign-in card. */
function Showcase() {
  const [i, setI] = useState(0);
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (paused || still) return;
    const t = window.setInterval(() => setI((n) => (n + 1) % SLIDES.length), SLIDE_MS);
    return () => window.clearInterval(t);
  }, [paused]);
  const slide = SLIDES[i];
  return (
    <aside className="relative hidden lg:flex lg:flex-col lg:justify-between"
           onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}>
      <div className="relative flex items-center gap-3 p-12">
        <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-white shadow-lg">
          <img src="/alphametricx-mark.png" alt="" className="h-8 w-8 object-contain" />
        </span>
        <span>
          <span className="block text-2xl font-bold tracking-tight text-white">AlphaMetricx</span>
          <span className="block text-xs font-semibold uppercase tracking-[0.18em] text-slate-300">Enterprise platform</span>
        </span>
      </div>
      <div className="relative p-12 pb-14" aria-roledescription="carousel" aria-label="What AlphaMetricx does">
        <div key={i} className="max-w-xl animate-[fadeUp_.5s_ease-out]" aria-live="polite">
          <span className="inline-block rounded-full border border-violet-300/40 bg-violet-500/20 px-3 py-1 text-xs font-bold uppercase tracking-wider text-violet-100">
            {slide.tag}
          </span>
          <h2 className="mt-4 text-4xl font-bold leading-tight tracking-tight text-white">{slide.title}</h2>
          <p className="mt-4 text-lg leading-relaxed text-slate-200">{slide.text}</p>
        </div>
        <div className="mt-8 flex gap-2">
          {SLIDES.map((s, n) => (
            <button key={s.tag} type="button" onClick={() => setI(n)} aria-label={`Show slide ${n + 1}: ${s.title}`}
                    aria-current={n === i}
                    className={`h-1.5 rounded-full transition-all ${n === i ? "w-12 bg-white" : "w-6 bg-white/35 hover:bg-white/60"}`} />
          ))}
        </div>
      </div>
      <style>{"@keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}"}</style>
    </aside>
  );
}

/** Sign in, plus Forgot password: email → 6-digit code → a one-time reset link is emailed (see auth/recovery.py). */
export function LoginPage() {
  const { login } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(true);
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

  const handleLogin = (e: React.FormEvent) => { e.preventDefault(); run(() => login(email, password, remember)); };
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
    <div className="relative min-h-screen bg-slate-950 bg-cover bg-center" style={{ backgroundImage: `url(${BACKGROUND})` }}>
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-slate-950/80 via-slate-950/45 to-slate-950/60" aria-hidden="true" />
      <div className="relative grid min-h-screen lg:grid-cols-2">
      <Showcase />
      <main className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-md rounded-3xl border border-white/25 bg-white/10 p-8 shadow-2xl shadow-black/40 backdrop-blur-xl sm:p-10">
          <div className="mb-10 flex items-center gap-3 lg:hidden">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-white">
              <img src="/alphametricx-mark.png" alt="" className="h-7 w-7 object-contain" />
            </span>
            <span className="text-xl font-bold tracking-tight text-white">AlphaMetricx</span>
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
            {mode === "login" ? "Sign in to your account" : "Reset your password"}
          </h1>
          <p className="mt-3 text-base text-slate-200">
            {mode === "login" ? "Welcome back. Access your executive media intelligence command center."
              : "We will confirm it is you before you choose a new password."}
          </p>
          <div className="mt-8">
            {error && <div className="mb-5 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>}
            {note && <div className="mb-5 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-800" role="status">{note}</div>}

            {mode === "login" && (
              <form onSubmit={handleLogin}>
                <label htmlFor="li-email" className={label}>Work Email Address</label>
                <input id="li-email" type="email" autoComplete="username" placeholder="name@company.com" value={email}
                       onChange={(e) => setEmail(e.target.value)} required className={`${input} mb-6`} />
                <div className="mb-2 flex items-baseline justify-between">
                  <label htmlFor="li-pw" className="text-sm font-semibold text-white">Password</label>
                  <button type="button" onClick={() => go("email")} className={link}>Forgot password?</button>
                </div>
                <div className="relative mb-5">
                  <input id="li-pw" type={showPassword ? "text" : "password"} autoComplete="current-password"
                         placeholder="Enter your password" value={password} onChange={(e) => setPassword(e.target.value)}
                         required className={`${input} pr-12`} />
                  <button type="button" onClick={() => setShowPassword((v) => !v)}
                          aria-label={showPassword ? "Hide password" : "Show password"} aria-pressed={showPassword}
                          className="absolute inset-y-0 right-0 flex w-12 items-center justify-center text-slate-500 hover:text-slate-800">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" />
                      {showPassword && <path d="M4 4l16 16" />}
                    </svg>
                  </button>
                </div>
                <label className="mb-7 flex cursor-pointer items-center gap-3 text-[15px] text-slate-100">
                  <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)}
                         className="h-5 w-5 rounded border-slate-300 accent-[#5B2C9D]" />
                  Keep me signed in for 30 days
                </label>
                <button type="submit" disabled={submitting} className={primary}>{submitting ? "Signing in..." : "Sign In"}</button>
              </form>
            )}

            {mode === "email" && (
              <form onSubmit={handleSendCode}>
                <p className="mb-5 text-sm text-slate-200">Enter your registered email. We will send a 6-digit code to confirm it.</p>
                <label htmlFor="fp-email" className={label}>Work Email Address</label>
                <input id="fp-email" type="email" autoComplete="username" placeholder="name@company.com" value={email}
                       onChange={(e) => setEmail(e.target.value)} required className={`${input} mb-6`} />
                <button type="submit" disabled={submitting} className={primary}>{submitting ? "Sending..." : "Send code"}</button>
                <button type="button" onClick={() => go("login")} className={`${link} mt-5 block`}>Back to sign in</button>
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
                <div className="mt-5 flex justify-between">
                  <button type="button" onClick={() => go("email")} className={link}>Send a new code</button>
                  <button type="button" onClick={() => go("login")} className={link}>Back to sign in</button>
                </div>
              </form>
            )}

            {mode === "sent" && (
              <>
                <p className="mb-6 text-sm text-slate-200">Open the link in the email to choose a new password. It works once and expires in 30 minutes.</p>
                <button type="button" onClick={() => go("login")} className={primary}>Back to sign in</button>
              </>
            )}
          </div>
        </div>
      </main>
      </div>
    </div>
  );
}
