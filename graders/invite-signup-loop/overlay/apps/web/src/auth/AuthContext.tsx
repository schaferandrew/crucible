import type { User } from "@conduit/shared";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setToken } from "../api/client";

interface AuthState {
  user: User | null;
  /** false until the saved session has been checked, so guards don't redirect too early */
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  /** sign in with a user the API just returned (e.g. from accepting an invite) */
  setSession: (user: User) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);
const STORAGE_KEY = "conduit.jwt";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (!saved) {
      setReady(true);
      return;
    }
    setToken(saved);
    api.currentUser().then(setUser, () => {
      localStorage.removeItem(STORAGE_KEY);
      setToken(null);
    }).finally(() => setReady(true));
  }, []);

  const setSession = useCallback((signedIn: User) => {
    localStorage.setItem(STORAGE_KEY, signedIn.token);
    setToken(signedIn.token);
    setUser(signedIn);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const signedIn = await api.login(email, password);
    localStorage.setItem(STORAGE_KEY, signedIn.token);
    setToken(signedIn.token);
    setUser(signedIn);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setToken(null);
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, ready, login, setSession, logout }), [user, ready, login, setSession, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
