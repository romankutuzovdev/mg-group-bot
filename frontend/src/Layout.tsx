import { Link, NavLink, Outlet } from "react-router-dom";
import { api } from "./api";
import { useAuth } from "./Auth";

export default function Layout() {
  const { user, logout, setUser } = useAuth();

  const toggleNotify = async () => {
    if (!user) return;
    const next = await api.patchMe({ notify: !user.notify });
    setUser(next);
  };

  return (
    <div className="shell">
      <header className="topbar">
        <Link to="/" className="brand">MG Group <span>CRM</span></Link>
        <nav className="topnav">
          <NavLink to="/" end className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Copart
          </NavLink>
          <NavLink to="/bidcars" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Bid.cars
          </NavLink>
          <NavLink to="/calc" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Калькулятор
          </NavLink>
          {user?.role === "admin" ? (
            <NavLink to="/team" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
              Команда
            </NavLink>
          ) : null}
        </nav>
        {user ? (
          <div className="topbar-user">
            <span className="topbar-name">{user.display_name}</span>
            <button className="btn ghost small" type="button" onClick={() => void toggleNotify()}>
              {user.notify ? "Бот: вкл" : "Бот: выкл"}
            </button>
            <button className="btn ghost small" type="button" onClick={() => void logout()}>
              Выйти
            </button>
          </div>
        ) : null}
      </header>
      <Outlet />
    </div>
  );
}
