import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { go } from "../App";
import { ErrorBox } from "../components/ui";
import type { Job, Settings } from "../types";

const TYPES = ["dentist", "clinic", "salon", "spa", "resort", "restaurant", "gym", "vet", "lawyer", "real estate", "auto repair", "school"];

export default function Find() {
  const [kind, setKind] = useState("dentist");
  const [places, setPlaces] = useState("Malolos, Calumpit, Guiguinto");
  const [source, setSource] = useState("auto");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    api.settings().then(setSettings).catch(() => undefined);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, []);

  const placeList = places.split(/[,\n]/).map((p) => p.trim()).filter(Boolean);
  const queries = placeList.map((p) => `${kind.trim()} in ${p}`);
  const running = job?.status === "running";

  async function start(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const j = await api.search(queries, source);
      setJob(j);
      timer.current = window.setInterval(async () => {
        const next = await api.job(j.id);
        setJob(next);
        if (next.status !== "running" && timer.current) {
          window.clearInterval(timer.current);
          timer.current = null;
        }
      }, 1000);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const pct = job && job.total ? Math.round((job.done / job.total) * 100) : 0;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Find leads</h1>
          <p className="muted">
            Search for businesses, find their emails, audit their websites and write the outreach — all in one go.
          </p>
        </div>
      </header>

      <form className="card form" onSubmit={start}>
        <label>
          <span>Business type</span>
          <input value={kind} onChange={(e) => setKind(e.target.value)} placeholder="dentist" required />
        </label>
        <div className="chips">
          {TYPES.map((t) => (
            <button type="button" key={t} className={`chip ${t === kind ? "active" : ""}`} onClick={() => setKind(t)}>
              {t}
            </button>
          ))}
        </div>

        <label>
          <span>Towns or cities</span>
          <textarea
            rows={2}
            value={places}
            onChange={(e) => setPlaces(e.target.value)}
            placeholder="Malolos, Calumpit, Guiguinto"
            required
          />
          <small className="muted">Separate with commas. Smaller towns or districts give better results than whole provinces.</small>
        </label>

        <label>
          <span>Data source</span>
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="auto">
              Automatic ({settings?.google_api_key_set ? "Google Maps" : "OpenStreetMap, free"})
            </option>
            <option value="osm">OpenStreetMap (free)</option>
            <option value="google" disabled={!settings?.google_api_key_set}>
              Google Maps {settings?.google_api_key_set ? "" : "(add key in Settings)"}
            </option>
          </select>
        </label>

        {queries.length > 0 && (
          <p className="muted small">
            Will search: {queries.map((q) => `“${q}”`).join(", ")}
          </p>
        )}

        <div>
          <button className="btn btn-primary" disabled={running || !queries.length}>
            {running ? "Searching…" : "Find leads"}
          </button>
        </div>
        <ErrorBox error={error} />
      </form>

      {job && (
        <section className="card">
          <h2>{job.status === "done" ? "Done" : job.status === "error" ? "Something went wrong" : job.stage}</h2>
          {job.status === "running" && (
            <>
              <div className="progress">
                <div className="progress-bar" style={{ width: `${job.total ? pct : 8}%` }} />
              </div>
              <p className="muted small">
                {job.total ? `Audited ${job.done} of ${job.total} websites` : "This can take a minute…"}
              </p>
            </>
          )}
          {job.status === "error" && <ErrorBox error={job.error} />}
          {job.status === "done" && (
            <div className="result-row">
              <div className="stat">
                <span className="stat-label">With a website</span>
                <span className="stat-value">{job.with_website}</span>
                <button className="btn" onClick={() => go("leads", { kind: "site" })}>
                  Review emails
                </button>
              </div>
              <div className="stat">
                <span className="stat-label">No website</span>
                <span className="stat-value">{job.no_website}</span>
                <button className="btn" onClick={() => go("leads", { kind: "nosite" })}>
                  Review messages
                </button>
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
