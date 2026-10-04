import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBox } from "../components/ui";
import type { Settings } from "../types";

const FIELDS = [
  { key: "sender_name", label: "Your name", placeholder: "Johnas Blasco" },
  { key: "sender_company", label: "Studio / company", placeholder: "Hala Web Studio" },
  { key: "sender_email", label: "Your email", placeholder: "you@yourstudio.com" },
  { key: "sender_address", label: "Business address", placeholder: "Malolos, Bulacan, Philippines", hint: "Anti-spam laws require an address in every cold email." },
  { key: "report_base_url", label: "Public report URL", placeholder: "https://hala-reports.pages.dev", hint: "Where you upload the downloaded reports (e.g. Cloudflare Pages). Email links use this." },
] as const;

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.settings().then(load).catch((e) => setError(e.message));
  }, []);

  function load(s: Settings) {
    setSettings(s);
    setForm({
      sender_name: s.sender_name,
      sender_company: s.sender_company,
      sender_email: s.sender_email,
      sender_address: s.sender_address,
      report_base_url: s.report_base_url,
      use_ai: s.use_ai,
      google_api_key: "",
      anthropic_api_key: "",
    });
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      load(await api.saveSettings(form));
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function clear(key: string) {
    load(await api.clearSecret(key));
  }

  if (!settings) return error ? <ErrorBox error={error} /> : <p className="muted">Loading…</p>;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Settings</h1>
          <p className="muted">Stored only on this computer.</p>
        </div>
      </header>

      <form className="card form" onSubmit={save}>
        <h2>You</h2>
        {FIELDS.map((f) => (
          <label key={f.key}>
            <span>{f.label}</span>
            <input
              value={form[f.key] ?? ""}
              placeholder={f.placeholder}
              onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
            />
            {"hint" in f && <small className="muted">{f.hint}</small>}
          </label>
        ))}

        <h2>API keys (optional)</h2>
        <SecretField
          label="Google Maps API key"
          hint="Bigger lead lists with reviews and ratings. Without it, Hala uses OpenStreetMap for free."
          isSet={settings.google_api_key_set}
          value={form.google_api_key}
          onChange={(v) => setForm({ ...form, google_api_key: v })}
          onClear={() => clear("google_api_key")}
        />
        <SecretField
          label="Anthropic API key"
          hint="Lets Claude write a custom email for each lead. Without it, a template is used."
          isSet={settings.anthropic_api_key_set}
          value={form.anthropic_api_key}
          onChange={(v) => setForm({ ...form, anthropic_api_key: v })}
          onClear={() => clear("anthropic_api_key")}
        />
        <label className="toggle">
          <input
            type="checkbox"
            checked={form.use_ai === "1"}
            onChange={(e) => setForm({ ...form, use_ai: e.target.checked ? "1" : "0" })}
          />
          <span>Use Claude to write emails when a key is set</span>
        </label>

        <div className="actions">
          <button className="btn btn-primary">Save settings</button>
          {saved && <span className="muted">Saved ✓</span>}
        </div>
        <ErrorBox error={error} />
      </form>
    </div>
  );
}

function SecretField(props: {
  label: string;
  hint: string;
  isSet: boolean;
  value: string;
  onChange: (v: string) => void;
  onClear: () => void;
}) {
  return (
    <label>
      <span>
        {props.label} {props.isSet && <em className="ok-text">· saved</em>}
      </span>
      <div className="inline-form">
        <input
          type="password"
          value={props.value}
          placeholder={props.isSet ? "•••••••• (leave blank to keep)" : "Paste key"}
          onChange={(e) => props.onChange(e.target.value)}
          autoComplete="off"
        />
        {props.isSet && (
          <button type="button" className="btn btn-small" onClick={props.onClear}>
            Remove
          </button>
        )}
      </div>
      <small className="muted">{props.hint}</small>
    </label>
  );
}
