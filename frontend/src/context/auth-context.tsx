import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { intelApi, SESSION_ENDED_EVENT, type AuthUser } from "../services/intel-api";
import { agentSocket } from "../services/ws";

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string, remember?: boolean) => Promise<void>;
  logout: () => Promise<void>;
  refreshMe: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshMe = async () => {
    try {
      const me = await intelApi.me();
      setUser(me);
    } catch {
      setUser(null);
    }
  };

  useEffect(() => {
    refreshMe().finally(() => setLoading(false));
    // a Super Admin signed everyone out: re-check, so an ended session lands on the sign-in page
    const off = agentSocket.onMessage((m) => { if (m.type === "sessions_revoked") void refreshMe(); });
    // any 401 means this session is over: show the sign-in page (not refreshMe: /me itself answers 401 then)
    const ended = () => setUser(null);
    window.addEventListener(SESSION_ENDED_EVENT, ended);
    return () => { off(); window.removeEventListener(SESSION_ENDED_EVENT, ended); };
  }, []);

  // signed in: keep the live socket open on every page, so "sessions_revoked" (and progress) always reaches this tab;
  // signed out: close it, so it stops asking for a ticket
  useEffect(() => {
    if (user) agentSocket.connect();
    else agentSocket.disconnect();
  }, [user]);

  const login = async (email: string, password: string, remember = false) => {
    const me = await intelApi.login(email, password, remember);
    setUser(me);
  };

  const logout = async () => {
    await intelApi.logout();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refreshMe }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
