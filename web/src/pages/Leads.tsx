import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { go } from "../App";
import LeadDrawer from "../components/LeadDrawer";
import { ErrorBox, ScoreBadge, StatusPill, TierBadge } from "../components/ui";
import type { Lead } from "../types";
import { STATUSES, STATUS_LABEL } from "../types";

export default function Leads({ query }: { query: URLSearchParams }) {
  const kind = query.get("kind") === "nosite" ? "nosite" : "site";
  const [status, setStatus] = useState(query.get("status") ?? "");
  const [q, setQ] = useState("");
  const [leads, setLeads] = useState<Lead[] | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setOpenId(null);
    setLeads(null);
  }, [kind]);

  const load = useCallback(() => {
    api
      .leads({ kind, status, q })
      .then(setLeads)
      .catch((e) => setError(e.message));
  }, [kind, status, q]);

  useEffect(() => {
    const t = window.setTimeout(load, 200);
    return () => window.clearTimeout(t);
  }, [load]);

  function onChanged(lead: Lead | null, removedId?: number) {
    setLeads((ls) => {
      if (!ls) return ls;
      if (removedId) return ls.filter((l) => l.id !== removedId);
      return ls.map((l) => (lead && l.id === lead.id ? lead : l));
    });
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Leads</h1>
          <p className="muted">Best leads first. Click a lead to see its audit and outreach.</p>
        </div>
        <div className="actions">
          <a className="btn" href={`/api/leads.csv?kind=${kind}`}>
            Export CSV
          </a>
          {kind === "site" && (
            <a className="btn" href="/api/reports.zip" title="Upload this to Cloudflare Pages">
              Download reports
            </a>
          )}
        </div>
      </header>

      <div className="tabs">
        <button className={`tab ${kind === "site" ? "active" : ""}`} onClick={() => go("leads", { kind: "site" })}>
          Has website
        </button>
        <button className={`tab ${kind === "nosite" ? "active" : ""}`} onClick={() => go("leads", { kind: "nosite" })}>
          No website
        </button>
      </div>

      <div className="filters">
        <input type="search" placeholder="Search name, city, email…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABEL[s]}
            </option>
          ))}
        </select>
      </div>

      <ErrorBox error={error} />
      {leads === null ? (
        <p className="muted">Loading…</p>
      ) : leads.length === 0 ? (
        <div className="card empty">
          <p>No leads here yet.</p>
          <button className="btn btn-primary" onClick={() => go("find")}>
            Find leads
          </button>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="table clickable">
            <thead>
              {kind === "site" ? (
                <tr>
                  <th>Business</th>
                  <th className="hide-sm">City</th>
                  <th className="num">Site</th>
                  <th>Tier</th>
                  <th className="hide-sm">Email</th>
                  <th>Status</th>
                </tr>
              ) : (
                <tr>
                  <th>Business</th>
                  <th className="hide-sm">City</th>
                  <th>Phone</th>
                  <th>Status</th>
                </tr>
              )}
            </thead>
            <tbody>
              {leads.map((l) => (
                <tr key={l.id} onClick={() => setOpenId(l.id)}>
                  <td>
                    <div className="cell-title">{l.name}</div>
                    <div className="cell-sub">{l.category}</div>
                  </td>
                  <td className="hide-sm">{l.city}</td>
                  {kind === "site" ? (
                    <>
                      <td className="num">
                        <ScoreBadge score={l.site_score} reachable={l.reachable} />
                      </td>
                      <td>
                        <TierBadge tier={l.tier} />
                      </td>
                      <td className="hide-sm">{l.email || <span className="muted">no email</span>}</td>
                    </>
                  ) : (
                    <td>{l.phone || <span className="muted">—</span>}</td>
                  )}
                  <td>
                    <StatusPill status={l.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {openId !== null && <LeadDrawer id={openId} onClose={() => setOpenId(null)} onChanged={onChanged} />}
    </div>
  );
}
