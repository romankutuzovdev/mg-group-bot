import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { api } from "./api";
import type { AuthUser } from "./types";

type AuthContextValue = {
  user: AuthUser | null;
  loading: boolean;
  configured: boolean;
  botUsername: string | null;
  telegramPollOk: boolean | null;
  telegramPollError: string | null;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
  setUser: (user: AuthUser | null) => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [configured, setConfigured] = useState(false);
  const [botUsername, setBotUsername] = useState<string | null>(null);
  const [telegramPollOk, setTelegramPollOk] = useState<boolean | null>(null);
  const [telegramPollError, setTelegramPollError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const data = await api.authConfig();
    setConfigured(data.configured);
    setBotUsername(data.bot_username);
    setUser(data.user);
    setTelegramPollOk(data.telegram_poll_ok ?? null);
    setTelegramPollError(data.telegram_poll_error ?? null);
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh().catch(() => setLoading(false));
  }, [refresh]);

  useEffect(() => {
    const onDenied = () => setUser(null);
    window.addEventListener("crm-unauthorized", onDenied);
    return () => window.removeEventListener("crm-unauthorized", onDenied);
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setUser(null);
    }
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        configured,
        botUsername,
        telegramPollOk,
        telegramPollError,
        refresh,
        logout,
        setUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return ctx;
}

export function RequireAuth() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) {
    return (
      <div className="auth-screen">
        <div className="hint">Загрузка…</div>
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}
