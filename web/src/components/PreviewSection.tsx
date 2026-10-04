import { useState } from "react";
import { api } from "../api";
import type { Lead } from "../types";
import { CopyButton, ErrorBox } from "./ui";

interface Saved {
  notes?: string;
  photos?: string[];
  facebook_url?: string;
  language?: string;
}

function parseSaved(raw: string): Saved {
  try {
    return raw ? (JSON.parse(raw) as Saved) : {};
  } catch {
    return {};
  }
}

export default function PreviewSection({ lead, onUpdated }: { lead: Lead; onUpdated: (l: Lead) => void }) {
  const saved = parseSaved(lead.preview_notes);
  const [notes, setNotes] = useState(saved.notes ?? "");
  const [facebook, setFacebook] = useState(saved.facebook_url ?? "");
  const [photos, setPhotos] = useState((saved.photos ?? []).join("\n"));
  const [language, setLanguage] = useState(saved.language ?? "English");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const url = lead.preview_token ? `${window.location.origin}/preview/${lead.preview_token}` : "";
  const local = /localhost|127\.0\.0\.1/.test(window.location.origin);
  const message = url
    ? `Hi ${lead.name}! I made a quick preview of what your website could look like:\n${url}\n\n` +
      "It's free to look at. If you like it, I can make it live for you this week. Want me to?"
    : "";

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.makePreview(lead.id, {
        notes,
        facebook_url: facebook.trim(),
        photos: photos.split(/\s+/).map((p) => p.trim()).filter(Boolean),
        language,
      });
      onUpdated(updated);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="drawer-section">
      <h3>Website preview</h3>
      <p className="muted small">
        A free one-page site for this business. Send the link: showing them their own site works far better than
        describing it.
      </p>
      <label>
        <span>
          Services, hours, specialties <span className="muted">(optional, from their Facebook page)</span>
        </span>
        <textarea
          rows={3}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder={"Braces\nTeeth whitening\nOpen Mon–Sat, 9am–6pm"}
        />
      </label>
      <label>
        <span>
          Facebook page link <span className="muted">(optional)</span>
        </span>
        <input value={facebook} onChange={(e) => setFacebook(e.target.value)} placeholder="https://facebook.com/…" />
      </label>
      <label>
        <span>
          Photo links <span className="muted">(optional, one per line; the first is the banner)</span>
        </span>
        <textarea rows={2} value={photos} onChange={(e) => setPhotos(e.target.value)} placeholder="https://…jpg" />
      </label>
      <label>
        <span>Language</span>
        <select value={language} onChange={(e) => setLanguage(e.target.value)}>
          <option>English</option>
          <option>Filipino</option>
          <option>Taglish</option>
        </select>
      </label>
      <div className="actions">
        <button className="btn btn-primary btn-small" onClick={generate} disabled={busy}>
          {busy ? "Generating…" : url ? "Regenerate preview" : "Generate preview"}
        </button>
        {busy && <span className="muted small">With Claude this can take up to a minute.</span>}
      </div>
      <ErrorBox error={error} />

      {url && (
        <div className="preview-result">
          <a href={url} target="_blank" rel="noreferrer" className="preview-link">
            {url} ↗
          </a>
          <div className="actions">
            <CopyButton text={url} label="Copy link" />
            <CopyButton text={message} label="Copy message with link" />
            <span className="muted small">Written by {lead.preview_source || "template"}</span>
          </div>
          {local && (
            <p className="alert alert-warn small">
              This link only works on your computer. Send links from your online Hala (Vercel) instead.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
