import { useEffect, useState } from "react";
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

export default function App() {
  const [route, setRoute] = useState(readHash);

  useEffect(() => {
    const onHash = () => setRoute(readHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

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
