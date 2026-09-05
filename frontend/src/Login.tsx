import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "./api";
import { useAuth } from "./Auth";

export default function Login() {
  const { user, loading, configured, botUsername, setUser, refresh } = useAuth();
  const [waiting, setWaiting] = useState(false);
  const [botUrl, setBotUrl] = useState("");
  const [error, setError] = useState("");
  const [expired, setExpired] = useState(false);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const start = async () => {
    setError("");
    setExpired(false);
    try {
      const data = await api.startLogin();
      setBotUrl(data.bot_url);
      setWaiting(true);
      window.open(data.bot_url, "_blank", "noopener,noreferrer");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось начать вход");
    }
  };

  useEffect(() => {
    if (!waiting || !botUrl) return undefined;
    const token = new URL(botUrl).searchParams.get("start");
    if (!token) return undefined;
    let stopped = false;
    const tick = async () => {
      try {
        const data = await api.pollLogin(token);
        if (stopped) return;
        if (data.status === "ok" && data.user) {
          setUser(data.user);
          setWaiting(false);
          return;
        }
        if (data.status === "expired" || data.status === "denied") {
          setWaiting(false);
          setExpired(true);
          setError(
            data.status === "denied"
              ? "Доступ отключён. Напишите администратору."
              : "Ссылка устарела — нажмите кнопку ещё раз.",
          );
        }
      } catch (err) {
        if (!stopped) setError(err instanceof Error ? err.message : "Ошибка входа");
      }
    };
    const timer = window.setInterval(() => void tick(), 1200);
    void tick();
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [waiting, botUrl, setUser]);

  if (loading) {
    return (
      <div className="auth-screen">
        <div className="hint">Загрузка…</div>
      </div>
    );
  }
  if (user) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="brand">
          MG Group <span>CRM</span>
        </div>
        <p className="hint">
          Вход через Telegram. После авторизации новые авто будут приходить в бот.
        </p>
        {!configured ? (
          <p className="error">
            Задайте TELEGRAM_BOT_TOKEN в файле .env и перезапустите python app.py
          </p>
        ) : (
          <>
            <button className="btn auth-btn" type="button" onClick={() => void start()} disabled={waiting && !expired}>
              {waiting && !expired ? "Жду подтверждение в Telegram…" : "Войти через Telegram"}
            </button>
            {waiting && !expired ? (
              <p className="hint">
                Нажмите <b>Start</b> боту{botUsername ? ` @${botUsername}` : ""} и вернитесь сюда.
                {botUrl ? (
                  <>
                    {" "}
                    <a href={botUrl} target="_blank" rel="noreferrer">
                      Открыть бота снова
                    </a>
                  </>
                ) : null}
              </p>
            ) : null}
          </>
        )}
        {error ? <p className="error">{error}</p> : null}
      </div>
    </div>
  );
}
