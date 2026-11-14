import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { intelApi, type AuthUser } from "../services/intel-api";

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
  }, []);

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
