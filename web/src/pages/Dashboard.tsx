import { useEffect, useState } from "react";
import { api } from "../api";
import { go } from "../App";
import { ErrorBox } from "../components/ui";
import type { Settings, Stats, Status } from "../types";
import { STATUS_LABEL } from "../types";

const FUNNEL: Status[] = ["new", "contacted", "replied", "meeting", "won", "lost"];

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.stats(), api.settings()])
      .then(([s, st]) => {
        setStats(s);
        setSettings(st);
      })
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorBox error={error} />;
  if (!stats || !settings) return <p className="muted">Loading…</p>;

  const contacted = FUNNEL.slice(1).reduce((n, s) => n + stats.by_status[s], 0);
  const replied = stats.by_status.replied + stats.by_status.meeting + stats.by_status.won;
  const replyRate = contacted ? Math.round((replied / contacted) * 100) : 0;

  const setup = [
    { done: !!settings.sender_name && !!settings.sender_address, label: "Add your name and address", page: "settings" as const },
    { done: stats.total > 0, label: "Run your first lead search", page: "find" as const },
    { done: contacted > 0, label: "Contact your first leads", page: "leads" as const },
  ];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p className="muted">Your pipeline at a glance.</p>
        </div>
        <button className="btn btn-primary" onClick={() => go("find")}>
          Find leads
        </button>
      </header>

      {setup.some((s) => !s.done) && (
        <section className="card">
          <h2>Getting started</h2>
          <ol className="checklist">
            {setup.map((s) => (
              <li key={s.label} className={s.done ? "done" : ""}>
                <span className="check">{s.done ? "✓" : ""}</span>
                {s.done ? s.label : <a href={`#/${s.page}`}>{s.label}</a>}
              </li>
            ))}
          </ol>
        </section>
      )}

      <section className="stat-grid">
        <Stat label="Total leads" value={stats.total} />
        <Stat label="Tier A leads" value={stats.tier_a} hint="Best to contact first" />
        <Stat label="No website" value={stats.no_website} hint="Need you the most" />
        <Stat label="Reply rate" value={`${replyRate}%`} hint={`${replied} of ${contacted} contacted`} />
      </section>

      <section className="card">
        <h2>Pipeline</h2>
        <div className="funnel">
          {FUNNEL.map((s) => (
            <a key={s} className="funnel-step" href={`#/leads?status=${s}`}>
              <span className="funnel-count">{stats.by_status[s]}</span>
              <span className="funnel-label">{STATUS_LABEL[s]}</span>
            </a>
          ))}
        </div>
      </section>

      <section className="card">
        <h2>What's working</h2>
        {stats.angles.length === 0 ? (
          <p className="muted">
            Once you mark leads as contacted and replied, you'll see which pitch angles get the most replies.
          </p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Pitch angle</th>
                <th className="num">Sent</th>
                <th className="num">Replies</th>
                <th className="num">Rate</th>
              </tr>
            </thead>
            <tbody>
              {stats.angles.map((a) => (
                <tr key={a.angle}>
                  <td>{a.angle}</td>
                  <td className="num">{a.sent}</td>
                  <td className="num">{a.replies}</td>
                  <td className="num">{Math.round((a.replies / a.sent) * 100)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {hint && <span className="stat-hint">{hint}</span>}
    </div>
  );
}
