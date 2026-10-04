import { useEffect, useState } from "react";
import { AUTH_EXPIRED } from "./api";
import { currentSession, loadAuthConfig, signOut, supabase } from "./auth";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Find from "./pages/Find";
import Leads from "./pages/Leads";
import QuickAudit from "./pages/QuickAudit";
import SettingsPage from "./pages/Settings";

const PAGES = [
  { id: "dashboard", label: "Dashboard", icon: "◧" },
  { id: "find", label: "Find leads", icon: "⌕" },
  { id: "leads", label: "Leads", icon: "☰" },
  { id: "audit", label: "Quick audit", icon: "✓" },
  { id: "settings", label: "Settings", icon: "⚙" },
] as const;

export type PageId = (typeof PAGES)[number]["id"];

function readHash(): { page: PageId; query: URLSearchParams } {
  const [path, qs] = window.location.hash.replace(/^#\/?/, "").split("?");
  const page = (PAGES.find((p) => p.id === path)?.id ?? "dashboard") as PageId;
  return { page, query: new URLSearchParams(qs ?? "") };
}

export function go(page: PageId, query?: Record<string, string>) {
  const qs = query ? `?${new URLSearchParams(query)}` : "";
  window.location.hash = `/${page}${qs}`;
}

type Gate =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "login"; notice: string | null }
  | { state: "in"; email: string | null };

export default function App() {
  const [route, setRoute] = useState(readHash);
  const [gate, setGate] = useState<Gate>({ state: "loading" });

  useEffect(() => {
    const onHash = () => setRoute(readHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  async function checkSession(notice: string | null = null) {
    try {
      const cfg = await loadAuthConfig();
      if (!cfg) return setGate({ state: "in", email: null });
      const session = await currentSession();
      setGate(session ? { state: "in", email: session.user.email ?? null } : { state: "login", notice });
    } catch (e) {
      setGate({ state: "error", message: (e as Error).message });
    }
  }

  useEffect(() => {
    checkSession();
    const onExpired = async () => {
      if (!supabase()) return;
      await signOut();
      setGate({ state: "login", notice: "Your session ended. Please log in again." });
    };
    window.addEventListener(AUTH_EXPIRED, onExpired);
    return () => window.removeEventListener(AUTH_EXPIRED, onExpired);
  }, []);

  if (gate.state === "loading") return <p className="muted center">Loading…</p>;
  if (gate.state === "error") return <div className="alert alert-error center">{gate.message}</div>;
  if (gate.state === "login") return <Login notice={gate.notice} onDone={() => checkSession()} />;

  return (
    <div className="shell">
      <nav className="sidebar">
        <div className="brand">
          <span className="logo">H</span>
          <span>Hala</span>
        </div>
        {PAGES.map((p) => (
          <a
            key={p.id}
            href={`#/${p.id}`}
            className={`nav-item ${route.page === p.id ? "active" : ""}`}
          >
            <span className="nav-icon" aria-hidden>
              {p.icon}
            </span>
            {p.label}
          </a>
        ))}
        {gate.email && (
          <div className="account">
            <span className="account-email" title={gate.email}>
              {gate.email}
            </span>
            <button
              className="btn btn-small"
              onClick={async () => {
                await signOut();
                setGate({ state: "login", notice: null });
              }}
            >
              Log out
            </button>
          </div>
        )}
      </nav>
      <main className="content">
        {route.page === "dashboard" && <Dashboard />}
        {route.page === "find" && <Find />}
        {route.page === "leads" && <Leads query={route.query} />}
        {route.page === "audit" && <QuickAudit />}
        {route.page === "settings" && <SettingsPage />}
      </main>
    </div>
  );
}
