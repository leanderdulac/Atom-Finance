import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { api, getAccessToken, setAccessToken } from '../services/api';

interface User {
  username: string;
  email?: string;
  role?: string;
}

interface AuthContextValue {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

// Credentials live in an HttpOnly refresh cookie + an in-memory access token.
// Nothing is written to localStorage, so a stored-XSS cannot lift the session.
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(() => getAccessToken());
  const [loading, setLoading] = useState(true);

  // Restore any existing session by refreshing through the HttpOnly cookie.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const restored = await api.refresh();
      if (cancelled) return;
      if (!restored) { setLoading(false); return; }
      setToken(getAccessToken());
      try {
        const me = await api.me();
        if (!cancelled) setUser(me);
      } catch {
        if (!cancelled) { setToken(null); setAccessToken(null); }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const data = await api.login(username, password);
    setAccessToken(data.access_token);
    setToken(data.access_token);
    setUser({ username: data.username, role: data.role });
  }, []);

  const register = useCallback(async (username: string, email: string, password: string) => {
    await api.register(username, email, password);
    await login(username, password);
  }, [login]);

  const logout = useCallback(async () => {
    try { await api.logout(); } catch { /* best-effort: clear locally regardless */ }
    setAccessToken(null);
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{
      user, token, isAuthenticated: !!user, loading, login, register, logout,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
