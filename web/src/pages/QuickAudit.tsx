import { useState } from "react";
import { api } from "../api";
import { ErrorBox, FindingList, ScoreBadge } from "../components/ui";
import type { AuditResult } from "../types";

export default function QuickAudit() {
  const [url, setUrl] = useState("");
  const [result, setResult] = useState<AuditResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResult(await api.audit(url));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Quick audit</h1>
          <p className="muted">Check any website, including your own work before handing it over.</p>
        </div>
      </header>

      <form className="card inline-form" onSubmit={run}>
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://somebusiness.com" required />
        <button className="btn btn-primary" disabled={busy}>
          {busy ? "Checking…" : "Audit"}
        </button>
      </form>
      <ErrorBox error={error} />

      {result && (
        <section className="card">
          <div className="audit-head">
            <ScoreBadge score={result.score} reachable={result.reachable} />
            <div>
              <h2>{result.page_title || result.url}</h2>
              <p className="muted small">
                {result.final_url || result.url}
                {result.load_seconds != null && ` · responded in ${result.load_seconds.toFixed(1)}s`}
              </p>
            </div>
          </div>
          <FindingList findings={result.findings} />
        </section>
      )}
    </div>
  );
}
