import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Lead, Status } from "../types";
import { STATUSES, STATUS_LABEL } from "../types";
import { CopyButton, ErrorBox, FindingList, ScoreBadge, TierBadge } from "./ui";

interface Props {
  id: number;
  onClose: () => void;
  onChanged: (lead: Lead | null, removedId?: number) => void;
}

export default function LeadDrawer({ id, onClose, onChanged }: Props) {
  const [lead, setLead] = useState<Lead | null>(null);
  const [draft, setDraft] = useState({ subject: "", body: "", message: "", notes: "", email: "" });
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<string | null>(null);

  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    api.lead(id).then(apply).catch((e) => setError(e.message));
  }, [id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function apply(l: Lead) {
    setLead(l);
    setDraft({ subject: l.subject, body: l.body, message: l.message, notes: l.notes, email: l.email });
  }

  async function save(changes: Partial<Lead>, label = "Saving") {
    setBusy(label);
    setError(null);
    try {
      const l = await api.updateLead(id, changes);
      apply(l);
      onChanged(l);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function refresh() {
    setBusy("Re-auditing");
    setError(null);
    try {
      if (lead && draft.email !== lead.email) await api.updateLead(id, { email: draft.email });
      const l = await api.refreshLead(id);
      apply(l);
      onChanged(l);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function remove() {
    if (!confirm(`Delete ${lead?.name}?`)) return;
    await api.deleteLead(id);
    onChanged(null, id);
    onClose();
  }

  if (!lead) {
    return (
      <Overlay onClose={onClose}>
        <ErrorBox error={error} />
        {!error && <p className="muted">Loading…</p>}
      </Overlay>
    );
  }

  const dirty =
    draft.subject !== lead.subject ||
    draft.body !== lead.body ||
    draft.message !== lead.message ||
    draft.notes !== lead.notes ||
    draft.email !== lead.email;

  const gmail =
    draft.email &&
    `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(draft.email)}&su=${encodeURIComponent(
      draft.subject,
    )}&body=${encodeURIComponent(draft.body)}`;

  return (
    <Overlay onClose={onClose}>
      <header className="drawer-head">
        <div>
          <h2>{lead.name}</h2>
          <p className="muted">
            {[capitalize(lead.category), lead.city].filter(Boolean).join(" · ")}
            {lead.rating && ` · ★ ${lead.rating}`}
            {lead.reviews && ` (${lead.reviews} reviews)`}
          </p>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </header>

      <div className="links">
        {lead.website && (
          <a href={lead.website} target="_blank" rel="noreferrer">
            Website ↗
          </a>
        )}
        {lead.has_website && (
          <a href={`/reports/${lead.id}`} target="_blank" rel="noreferrer">
            Audit report ↗
          </a>
        )}
        {lead.maps_url && (
          <a href={lead.maps_url} target="_blank" rel="noreferrer">
            Map ↗
          </a>
        )}
        {lead.facebook_search && (
          <a href={lead.facebook_search} target="_blank" rel="noreferrer">
            Find on Facebook ↗
          </a>
        )}
        {lead.phone && <a href={`tel:${lead.phone}`}>Call {lead.phone}</a>}
      </div>

      <section className="drawer-section">
        <h3>Status</h3>
        <div className="segmented">
          {STATUSES.map((s: Status) => (
            <button
              key={s}
              className={lead.status === s ? "active" : ""}
              onClick={() => save({ status: s }, "Updating")}
              disabled={!!busy}
            >
              {STATUS_LABEL[s]}
            </button>
          ))}
        </div>
      </section>

      {lead.has_website ? (
        <>
          <section className="drawer-section">
            <div className="row-between">
              <h3>Website check</h3>
              <button className="btn btn-small" onClick={refresh} disabled={!!busy}>
                {busy === "Re-auditing" ? "Re-auditing…" : "Re-audit"}
              </button>
            </div>
            <div className="kv">
              <span>Site score</span>
              <ScoreBadge score={lead.site_score} reachable={lead.reachable} />
              <span>Lead tier</span>
              <TierBadge tier={lead.tier} />
              {lead.reasons && (
                <>
                  <span>Why</span>
                  <span className="muted">{lead.reasons}</span>
                </>
              )}
            </div>
            <FindingList findings={lead.findings} />
          </section>

          <section className="drawer-section">
            <h3>Email</h3>
            {lead.tier === "skip" && !lead.body ? (
              <p className="muted">
                No email written: {lead.reasons || "this lead was skipped"}. Add an email address below and re-audit to
                generate one.
              </p>
            ) : null}
            <label>
              <span>To</span>
              <input value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} placeholder="owner@business.com" />
            </label>
            <label>
              <span>Subject</span>
              <input value={draft.subject} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} />
            </label>
            <label>
              <span>Body</span>
              <textarea rows={12} value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
            </label>
            {lead.body.includes("localhost") && (
              <p className="alert alert-warn small">
                The report link points to your computer. Set a public report URL in Settings, then re-audit, before
                sending.
              </p>
            )}
            <div className="actions">
              <CopyButton text={draft.body} label="Copy email" />
              {gmail && (
                <a
                  className="btn btn-small"
                  href={gmail}
                  target="_blank"
                  rel="noreferrer"
                  onClick={() => lead.status === "new" && save({ status: "contacted" }, "Updating")}
                >
                  Open in Gmail
                </a>
              )}
              {lead.pitch_source && <span className="muted small">Written by {lead.pitch_source}</span>}
            </div>
          </section>
        </>
      ) : (
        <section className="drawer-section">
          <h3>Message (Messenger / SMS)</h3>
          <textarea rows={7} value={draft.message} onChange={(e) => setDraft({ ...draft, message: e.target.value })} />
          <div className="actions">
            <CopyButton text={draft.message} label="Copy message" />
            {lead.facebook_search && (
              <a className="btn btn-small" href={lead.facebook_search} target="_blank" rel="noreferrer">
                Find their Facebook page
              </a>
            )}
          </div>
        </section>
      )}

      <section className="drawer-section">
        <h3>Notes</h3>
        <textarea
          rows={3}
          value={draft.notes}
          onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
          placeholder="Called, talked to Dr. Reyes, follow up Friday…"
        />
      </section>

      <ErrorBox error={error} />

      <footer className="drawer-foot">
        <button className="btn btn-danger" onClick={remove}>
          Delete
        </button>
        <button className="btn btn-primary" disabled={!dirty || !!busy} onClick={() => save(draft)}>
          {busy === "Saving" ? "Saving…" : dirty ? "Save changes" : "Saved"}
        </button>
      </footer>
    </Overlay>
  );
}

function Overlay({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="drawer" role="dialog" aria-modal="true">
        {children}
      </aside>
    </div>
  );
}

function capitalize(s: string) {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}
