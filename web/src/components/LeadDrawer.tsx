import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Lead, Settings, Status } from "../types";
import { STATUSES, STATUS_LABEL } from "../types";
import PreviewSection from "./PreviewSection";
import { CopyButton, ErrorBox, FindingList, ScoreBadge, TierBadge } from "./ui";

interface Props {
  id: number;
  onClose: () => void;
  onChanged: (lead: Lead | null, removedId?: number) => void;
}

type Draft = { subject: string; body: string; message: string; notes: string; email: string };
const DRAFT_KEYS: (keyof Draft)[] = ["subject", "body", "message", "notes", "email"];
const AUTOSAVE_MS = 800;

function draftOf(l: Lead): Draft {
  return { subject: l.subject, body: l.body, message: l.message, notes: l.notes, email: l.email };
}

export default function LeadDrawer({ id, onClose, onChanged }: Props) {
  const [lead, setLead] = useState<Lead | null>(null);
  const [draft, setDraft] = useState<Draft>({ subject: "", body: "", message: "", notes: "", email: "" });
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ text: string; undo: boolean } | null>(null);
  const [mail, setMail] = useState<Settings["email_sending"] | null>(null);

  // What the server has, so auto-save only sends real changes.
  const saved = useRef<Draft | null>(null);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const onChangedRef = useRef(onChanged);
  onChangedRef.current = onChanged;

  function apply(l: Lead) {
    setLead(l);
    const d = draftOf(l);
    saved.current = d;
    setDraft(d);
  }

  useEffect(() => {
    api.lead(id).then(apply).catch((e) => setError(e.message));
    api.settings().then((s) => setMail(s.email_sending)).catch(() => undefined);
  }, [id]);

  /** Save whatever changed since the last save. Safe to call any time. */
  const flush = useCallback(async (): Promise<Lead | null> => {
    const base = saved.current;
    if (!base) return null;
    const current = draftRef.current;
    const changes = Object.fromEntries(DRAFT_KEYS.filter((k) => current[k] !== base[k]).map((k) => [k, current[k]]));
    if (Object.keys(changes).length === 0) return null;
    setSaveState("saving");
    try {
      const l = await api.updateLead(id, changes);
      saved.current = { ...base, ...(changes as Partial<Draft>) };
      setLead(l); // not apply(): keep anything typed while this was saving
      onChangedRef.current(l);
      setSaveState("saved");
      return l;
    } catch (e) {
      setSaveState("error");
      setError((e as Error).message);
      return null;
    }
  }, [id]);

  // Auto-save shortly after typing stops.
  useEffect(() => {
    if (!saved.current) return;
    const changed = DRAFT_KEYS.some((k) => draft[k] !== saved.current![k]);
    if (!changed) return;
    const t = window.setTimeout(flush, AUTOSAVE_MS);
    return () => window.clearTimeout(t);
  }, [draft, flush]);

  const close = useCallback(() => {
    flush(); // finish saving in the background
    onClose();
  }, [flush, onClose]);

  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function setStatus(status: Status) {
    setError(null);
    await flush();
    try {
      const l = await api.updateLead(id, { status });
      setLead(l);
      onChanged(l);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function showToast(text: string, undo: boolean) {
    setToast({ text, undo });
    window.setTimeout(() => setToast(null), 8000);
  }

  /** Copy / Gmail / Call / Facebook: a New lead becomes Contacted (undoable). */
  async function markContacted() {
    if (!lead || lead.status !== "new") return;
    await setStatus("contacted");
    showToast("Marked as contacted", true);
  }

  async function undoContacted() {
    setToast(null);
    await setStatus("new");
  }

  async function sendEmail() {
    if (!lead) return;
    const again = lead.emails_sent > 0;
    if (!confirm(`${again ? "Send this email again" : "Send this email"} to ${draft.email}?`)) return;
    setBusy("Sending");
    setError(null);
    try {
      await flush(); // send exactly what's on screen
      const l = await api.sendEmail(id);
      setLead(l);
      onChanged(l);
      setMail((m) => (m ? { ...m, sent_last_24h: m.sent_last_24h + 1 } : m));
      showToast(`Email sent to ${l.email}`, false);
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
      await flush();
      apply(await api.refreshLead(id));
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
      <Overlay onClose={close}>
        <ErrorBox error={error} />
        {!error && <p className="muted">Loading…</p>}
      </Overlay>
    );
  }

  const gmailUrl =
    `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(draft.email)}` +
    `&su=${encodeURIComponent(draft.subject)}&body=${encodeURIComponent(draft.body)}`;

  return (
    <Overlay onClose={close}>
      <header className="drawer-head">
        <div>
          <h2>{lead.name}</h2>
          <p className="muted">
            {[capitalize(lead.category), lead.city].filter(Boolean).join(" · ")}
            {lead.rating && ` · ★ ${lead.rating}`}
            {lead.reviews && ` (${lead.reviews} reviews)`}
          </p>
        </div>
        <button className="icon-btn" onClick={close} aria-label="Close">
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
          <a href={`/reports/${lead.report_token}`} target="_blank" rel="noreferrer">
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
        {lead.phone && (
          <a href={`tel:${lead.phone}`} onClick={markContacted}>
            Call {lead.phone}
          </a>
        )}
      </div>

      <section className="drawer-section">
        <h3>Status</h3>
        <div className="segmented">
          {STATUSES.map((s: Status) => (
            <button key={s} className={lead.status === s ? "active" : ""} onClick={() => setStatus(s)} disabled={!!busy}>
              {STATUS_LABEL[s]}
            </button>
          ))}
        </div>
        {lead.contacted_at && <ContactedNote at={lead.contacted_at} status={lead.status} />}
        {lead.email_sent_at && (
          <p className="small muted" style={{ margin: 0 }}>
            Email sent {new Date(lead.email_sent_at).toLocaleString()}
            {lead.emails_sent > 1 && ` (${lead.emails_sent} times)`}
          </p>
        )}
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
              <input
                value={draft.email}
                onChange={(e) => setDraft({ ...draft, email: e.target.value })}
                placeholder="owner@business.com"
              />
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
                The report link points to your computer. Open Hala from your Vercel site and re-audit before sending.
              </p>
            )}
            <div className="actions">
              <CopyButton text={draft.body} label="Copy email" onCopied={markContacted} />
              {lead.pitch_source && <span className="muted small">Written by {lead.pitch_source}</span>}
            </div>
          </section>
        </>
      ) : (
        <section className="drawer-section">
          <h3>Message (Messenger / SMS)</h3>
          <textarea rows={7} value={draft.message} onChange={(e) => setDraft({ ...draft, message: e.target.value })} />
          <div className="actions">
            <CopyButton text={draft.message} label="Copy message" onCopied={markContacted} />
          </div>
        </section>
      )}

      <PreviewSection
        lead={lead}
        onContacted={markContacted}
        onUpdated={(l) => {
          setLead(l);
          onChanged(l);
        }}
      />

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
        <div className="actions">
          <SaveIndicator state={saveState} />
          <SendButton
            lead={lead}
            draft={draft}
            mail={mail}
            busy={busy}
            gmailUrl={gmailUrl}
            onSendEmail={sendEmail}
            onContacted={markContacted}
          />
        </div>
      </footer>
      {toast && (
        <div className="toast" role="status">
          <span>✓ {toast.text}</span>
          {toast.undo && (
            <button className="btn btn-small" onClick={undoContacted}>
              Undo
            </button>
          )}
        </div>
      )}
    </Overlay>
  );
}

/** The one main action, chosen for this lead. */
function SendButton(props: {
  lead: Lead;
  draft: Draft;
  mail: Settings["email_sending"] | null;
  busy: string;
  gmailUrl: string;
  onSendEmail: () => void;
  onContacted: () => void;
}) {
  const { lead, draft, mail, busy } = props;
  const again = lead.status !== "new";

  if (!lead.has_website) {
    // Facebook leads: copy the message and open their page in one click.
    return (
      <button
        className="btn btn-primary"
        disabled={!draft.message}
        title="Copies the message and opens their Facebook page. Paste it in Messenger."
        onClick={() => {
          window.open(facebookPage(lead), "_blank", "noopener"); // must happen inside the click
          navigator.clipboard.writeText(draft.message).catch(() => undefined);
          props.onContacted();
        }}
      >
        {again ? "Copy & open Facebook again" : "Send message: copy & open Facebook"}
      </button>
    );
  }

  if (!draft.email) {
    return (
      <button className="btn btn-primary" disabled title="Add their email address above">
        Send email (add their email)
      </button>
    );
  }

  if (mail?.configured) {
    const left = mail.limit - mail.sent_last_24h;
    return (
      <button
        className="btn btn-primary"
        onClick={props.onSendEmail}
        disabled={!!busy || left <= 0 || !draft.subject || !draft.body}
        title={left <= 0 ? "Daily limit reached. Try again tomorrow." : `${left} of ${mail.limit} left today`}
      >
        {busy === "Sending" ? "Sending…" : lead.emails_sent > 0 ? "Send again" : `Send email (${left} left today)`}
      </button>
    );
  }

  return (
    <a
      className="btn btn-primary"
      href={props.gmailUrl}
      target="_blank"
      rel="noreferrer"
      onClick={props.onContacted}
      title="Opens Gmail with this email ready. Set up sending in Settings to send from Hala directly."
    >
      {again ? "Open in Gmail again" : "Send via Gmail"}
    </a>
  );
}

/** Their actual page if you saved one in the preview section, else a Facebook search. */
function facebookPage(lead: Lead): string {
  try {
    const saved = JSON.parse(lead.preview_notes || "{}") as { facebook_url?: string };
    if (saved.facebook_url && /^https?:\/\//.test(saved.facebook_url)) return saved.facebook_url;
  } catch {
    /* no saved page */
  }
  return lead.facebook_search;
}

function SaveIndicator({ state }: { state: "idle" | "saving" | "saved" | "error" }) {
  if (state === "idle") return null;
  const text = { saving: "Saving…", saved: "Saved ✓", error: "Not saved" }[state];
  return <span className={`small ${state === "error" ? "error-text" : "muted"}`}>{text}</span>;
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

function ContactedNote({ at, status }: { at: string; status: Status }) {
  const when = new Date(at);
  const days = Math.floor((Date.now() - when.getTime()) / 86_400_000);
  const ago = days <= 0 ? "today" : days === 1 ? "yesterday" : `${days} days ago`;
  const due = status === "contacted" && days >= 3;
  return (
    <p className={`small ${due ? "alert alert-warn" : "muted"}`} style={{ margin: 0 }}>
      Contacted {when.toLocaleDateString()} ({ago})
      {due && ". No reply yet, so it's a good time to follow up."}
    </p>
  );
}
