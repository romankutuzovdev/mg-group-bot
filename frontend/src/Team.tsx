import { useEffect, useState } from "react";
import { api } from "./api";
import { useAuth } from "./Auth";
import type { AuthUser } from "./types";

export default function Team() {
  const { user } = useAuth();
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [error, setError] = useState("");

  const load = async () => {
    try {
      setUsers(await api.users());
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить команду");
    }
  };

  useEffect(() => {
    void load();
  }, []);

  if (user?.role !== "admin") {
    return (
      <main className="page-main">
        <p className="error">Только администратор может управлять командой.</p>
      </main>
    );
  }

  return (
    <main className="page-main team-page">
      <div className="brand" style={{ fontSize: 26 }}>
        Команда
      </div>
      <p className="hint">
        Кто вошёл через Telegram, тот в CRM. Новые авто уходят всем, у кого включены уведомления.
      </p>
      {error ? <p className="error">{error}</p> : null}
      <div className="team-list">
        {users.map((item) => (
          <div className={`team-card ${item.enabled ? "" : "gone"}`} key={item.id}>
            <div>
              <strong>{item.display_name}</strong>
              <div className="meta">
                {item.username ? `@${item.username}` : `id ${item.telegram_id}`}
                {" · "}
                {item.role === "admin" ? "админ" : "пользователь"}
                {!item.enabled ? " · отключён" : ""}
              </div>
            </div>
            <div className="row">
              <button
                className="btn ghost small"
                type="button"
                onClick={() => void api.patchUser(item.id, { notify: !item.notify }).then(load)}
              >
                {item.notify ? "Уведомления вкл" : "Уведомления выкл"}
              </button>
              <button
                className="btn ghost small"
                type="button"
                onClick={() =>
                  void api.patchUser(item.id, { role: item.role === "admin" ? "user" : "admin" }).then(load)
                }
              >
                {item.role === "admin" ? "Снять админа" : "Сделать админом"}
              </button>
              <button
                className="btn ghost small"
                type="button"
                onClick={() => void api.patchUser(item.id, { enabled: !item.enabled }).then(load)}
              >
                {item.enabled ? "Отключить" : "Включить"}
              </button>
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}
