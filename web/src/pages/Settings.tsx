import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBox } from "../components/ui";
import type { Settings } from "../types";

const FIELDS = [
  { key: "sender_name", label: "Your name", placeholder: "Johnas Blasco" },
  { key: "sender_company", label: "Studio / company", placeholder: "Hala Web Studio" },
  { key: "sender_email", label: "Your email", placeholder: "you@yourstudio.com" },
  { key: "sender_address", label: "Business address", placeholder: "Malolos, Bulacan, Philippines", hint: "Anti-spam laws require an address in every cold email." },
  { key: "report_base_url", label: "External report URL (optional)", placeholder: "Leave blank", hint: "Leave blank: report links use this Hala site. Only fill this in if you host the downloaded reports somewhere else." },
] as const;

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [test, setTest] = useState<{ ok: boolean; message: string; provider?: string; model?: string } | null>(null);
  const [testing, setTesting] = useState(false);
  const [mailTest, setMailTest] = useState<{ ok: boolean; message: string } | null>(null);
  const [mailTesting, setMailTesting] = useState(false);

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
      ai_provider: s.ai_provider,
      ai_model: s.ai_model,
      ai_base_url: s.ai_base_url,
      google_api_key: "",
      smtp_user: s.smtp_user,
      smtp_password: "",
      smtp_host: s.smtp_host,
      smtp_port: s.smtp_port,
      daily_send_limit: s.daily_send_limit,
      ...Object.fromEntries(s.ai_providers.map((p) => [`${p.id}_api_key`, ""])),
    });
  }

  async function testEmail() {
    setMailTesting(true);
    setMailTest(null);
    setError(null);
    try {
      load(await api.saveSettings(form));
      setMailTest(await api.testEmail());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setMailTesting(false);
    }
  }

  async function testAI() {
    setTesting(true);
    setTest(null);
    setError(null);
    try {
      load(await api.saveSettings(form)); // test what's on screen, saved
      setTest(await api.testAI());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setTesting(false);
    }
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
          <p className="muted">Saved in your Hala database. Keys are never shown again after saving.</p>
        </div>
      </header>

      <form className="card form" onSubmit={save} autoComplete="off">
        <h2>You</h2>
        {FIELDS.map((f) => (
          <label key={f.key}>
            <span>{f.label}</span>
            <input
              value={form[f.key] ?? ""}
              name={`hala-${f.key}`}
              autoComplete="off"
              data-lpignore="true"
              data-1p-ignore="true"
              placeholder={f.placeholder}
              onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
            />
            {"hint" in f && <small className="muted">{f.hint}</small>}
          </label>
        ))}

        <h2>Email sending (optional)</h2>
        <p className="muted small" style={{ marginTop: -8 }}>
          Lets the Send button email leads straight from your Gmail. Without it, Send opens Gmail with the email ready.
        </p>
        <label>
          <span>Gmail address</span>
          <input
            type="email"
            name="hala-smtp-user"
            autoComplete="off"
            data-lpignore="true"
            data-1p-ignore="true"
            value={form.smtp_user ?? ""}
            onChange={(e) => setForm({ ...form, smtp_user: e.target.value })}
            placeholder="you@gmail.com"
          />
        </label>
        <SecretField
          label="Gmail App Password"
          hint="Not your normal password. Turn on 2-Step Verification, then create one at myaccount.google.com/apppasswords (16 letters)."
          isSet={!!settings.smtp_password_set}
          value={form.smtp_password ?? ""}
          onChange={(v) => setForm({ ...form, smtp_password: v })}
          onClear={() => clear("smtp_password")}
        />
        <label>
          <span>Daily limit</span>
          <input
            type="number"
            min={1}
            max={100}
            value={form.daily_send_limit ?? ""}
            onChange={(e) => setForm({ ...form, daily_send_limit: e.target.value })}
            placeholder="25"
          />
          <small className="muted">
            Max emails per 24 hours ({settings.email_sending.sent_last_24h} sent so far). Keep it low: Gmail flags
            accounts that send many cold emails.
          </small>
        </label>
        <details>
          <summary className="muted small">Not using Gmail? Mail server settings</summary>
          <div className="form" style={{ marginTop: 12 }}>
            <label>
              <span>SMTP host</span>
              <input
                value={form.smtp_host ?? ""}
                onChange={(e) => setForm({ ...form, smtp_host: e.target.value })}
                placeholder="smtp.gmail.com"
              />
            </label>
            <label>
              <span>Port</span>
              <input
                value={form.smtp_port ?? ""}
                onChange={(e) => setForm({ ...form, smtp_port: e.target.value })}
                placeholder="465"
              />
            </label>
          </div>
        </details>
        <div className="actions">
          <button type="button" className="btn" onClick={testEmail} disabled={mailTesting}>
            {mailTesting ? "Sending test…" : "Save & send test email to myself"}
          </button>
          {mailTest && (
            <span className={`test-result ${mailTest.ok ? "ok-text" : "error-text"}`}>
              {mailTest.ok ? "✓ " : "✗ "}
              {mailTest.message}
            </span>
          )}
        </div>

        <h2>Lead search (optional)</h2>
        <SecretField
          label="Google Maps API key"
          hint="Bigger lead lists with reviews and ratings. Without it, Hala uses OpenStreetMap for free."
          isSet={settings.google_api_key_set}
          value={form.google_api_key}
          onChange={(v) => setForm({ ...form, google_api_key: v })}
          onClear={() => clear("google_api_key")}
        />

        <h2>AI writing (optional)</h2>
        <p className="muted small" style={{ marginTop: -8 }}>
          Writes each email and website preview. Without AI, Hala uses good templates, so this is optional.
        </p>
        <label className="toggle">
          <input
            type="checkbox"
            checked={form.use_ai === "1"}
            onChange={(e) => setForm({ ...form, use_ai: e.target.checked ? "1" : "0" })}
          />
          <span>Use AI to write emails and previews</span>
        </label>
        {form.use_ai === "1" && (
          <AISettings settings={settings} form={form} setForm={setForm} clear={clear} />
        )}
        {form.use_ai === "1" && (
          <div className="actions">
            <button type="button" className="btn" onClick={testAI} disabled={testing}>
              {testing ? "Testing…" : "Save & test AI"}
            </button>
            {test && (
              <span className={`test-result ${test.ok ? "ok-text" : "error-text"}`}>
                {test.ok ? `✓ Works (${test.provider}, ${test.model}): “${test.message}”` : `✗ ${test.message}`}
              </span>
            )}
          </div>
        )}

        <div className="actions">
          <button className="btn btn-primary">Save settings</button>
          {saved && <span className="muted">Saved ✓</span>}
        </div>
        <ErrorBox error={error} />
      </form>
    </div>
  );
}

function AISettings({
  settings,
  form,
  setForm,
  clear,
}: {
  settings: Settings;
  form: Record<string, string>;
  setForm: (f: Record<string, string>) => void;
  clear: (key: string) => void;
}) {
  const provider = settings.ai_providers.find((p) => p.id === form.ai_provider) ?? settings.ai_providers[0];
  const keyName = `${provider.id}_api_key` as `${string}_api_key`;
  const isCustom = provider.id === "custom";
  return (
    <>
      <label>
        <span>AI provider</span>
        <select
          value={provider.id}
          onChange={(e) => setForm({ ...form, ai_provider: e.target.value, ai_model: "" })}
        >
          {settings.ai_providers.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
              {settings[`${p.id}_api_key_set`] ? " ✓" : ""}
            </option>
          ))}
        </select>
        <small className="muted">
          {PROVIDER_HINTS[provider.id] ?? ""}
          {provider.key_url && (
            <>
              {" "}
              <a href={provider.key_url} target="_blank" rel="noreferrer">
                Get a key ↗
              </a>
            </>
          )}
        </small>
      </label>
      {isCustom && (
        <label>
          <span>Base URL</span>
          <input
            value={form.ai_base_url ?? ""}
            onChange={(e) => setForm({ ...form, ai_base_url: e.target.value })}
            placeholder="http://localhost:11434/v1"
          />
          <small className="muted">Any OpenAI-compatible API. Ollama on your computer only works with hala serve.</small>
        </label>
      )}
      <SecretField
        label={`${provider.label} API key${isCustom ? " (if needed)" : ""}`}
        hint="Each provider's key is saved separately, so you can switch back and forth."
        isSet={!!settings[`${keyName}_set`]}
        value={form[keyName] ?? ""}
        onChange={(v) => setForm({ ...form, [keyName]: v })}
        onClear={() => clear(keyName)}
      />
      <ModelPicker settings={settings} form={form} setForm={setForm} />
    </>
  );
}

function ModelPicker({
  settings,
  form,
  setForm,
}: {
  settings: Settings;
  form: Record<string, string>;
  setForm: (f: Record<string, string>) => void;
}) {
  const [list, setList] = useState<{ models: string[]; automatic: string | null; error: string | null } | null>(
    null,
  );
  const savedProvider = form.ai_provider === settings.ai_provider;
  const keySaved = !!settings[`${settings.ai_provider}_api_key_set`] || settings.ai_provider === "custom";

  useEffect(() => {
    setList(null);
    if (!savedProvider || !keySaved) return;
    api.models().then(setList).catch((e) => setList({ models: [], automatic: null, error: e.message }));
    // Reload when the saved provider/key/base URL change (settings object is replaced on save).
  }, [settings, savedProvider, keySaved]);

  const current = form.ai_model ?? "";
  const options = list?.models ?? [];
  const showTextInput = !!list?.error || (list !== null && options.length === 0);

  return (
    <label>
      <span>Model</span>
      {showTextInput ? (
        <input
          value={current}
          onChange={(e) => setForm({ ...form, ai_model: e.target.value })}
          placeholder="Automatic"
        />
      ) : (
        <select value={current} onChange={(e) => setForm({ ...form, ai_model: e.target.value })}>
          <option value="">
            Automatic{list?.automatic ? ` (best available: ${list.automatic})` : " (recommended)"}
          </option>
          {current && !options.includes(current) && <option value={current}>{current} (not in your list)</option>}
          {options.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      )}
      <small className="muted">
        {!savedProvider || !keySaved
          ? "Save your key to see the models it can use. Automatic picks a good current one for you."
          : list === null
            ? "Loading the models your key can use…"
            : list.error
              ? `Couldn't load the model list: ${list.error}`
              : "Automatic picks the best current model, so renamed or retired models won't break anything."}
      </small>
    </label>
  );
}

const PROVIDER_HINTS: Record<string, string> = {
  anthropic: "Claude: best at following the “don't make things up” rules. Paid per use.",
  gemini: "Free tier with daily limits. Good at Filipino and Taglish.",
  groq: "Free tier with rate limits. Very fast; open models.",
  openrouter: "One key, many models, including some free ones (model names ending in :free).",
  openai: "ChatGPT models. Paid per use.",
  custom: "Any server that speaks the OpenAI API, such as Ollama or LM Studio.",
};

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
        {/* Not type="password": browsers treat this page like a login form and autofill saved
            passwords into password fields. A masked text field isn't autofilled. */}
        <input
          type="text"
          className="masked"
          name={`hala-key-${props.label.replace(/\W+/g, "-").toLowerCase()}`}
          value={props.value}
          placeholder={props.isSet ? "•••••••• (leave blank to keep)" : "Paste key"}
          onChange={(e) => props.onChange(e.target.value)}
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={false}
          data-lpignore="true"
          data-1p-ignore="true"
          data-bwignore="true"
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
