import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { go } from "../App";
import { ErrorBox } from "../components/ui";
import PH from "../data/ph-locations.json";
import type { Job, Settings } from "../types";

const PROVINCES = PH as { province: string; cities: string[] }[];
const SAVED_KEY = "hala.find.location";

function loadSaved(): { province: string; cities: string[] } {
  try {
    const v = JSON.parse(localStorage.getItem(SAVED_KEY) ?? "");
    if (v && typeof v.province === "string" && Array.isArray(v.cities)) return v;
  } catch {
    /* nothing saved */
  }
  return { province: "Bulacan", cities: ["Malolos City"] };
}

const TYPES = ["dentist", "clinic", "salon", "spa", "resort", "restaurant", "gym", "vet", "lawyer", "real estate", "auto repair", "school"];

export default function Find() {
  const [kind, setKind] = useState("dentist");
  const saved = useMemo(loadSaved, []);
  const [province, setProvince] = useState(saved.province);
  const [cities, setCities] = useState<string[]>(saved.cities);
  const [filter, setFilter] = useState("");
  const [extra, setExtra] = useState("");
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

  const provinceCities = PROVINCES.find((p) => p.province === province)?.cities ?? [];
  const shown = provinceCities.filter((c) => c.toLowerCase().includes(filter.toLowerCase()));
  const extraPlaces = extra.split(/[,\n]/).map((p) => p.trim()).filter(Boolean);
  const queries = [
    ...cities.map((c) => `${kind.trim()} in ${c}, ${province}, Philippines`),
    ...extraPlaces.map((p) => `${kind.trim()} in ${p}`),
  ];

  useEffect(() => {
    try {
      localStorage.setItem(SAVED_KEY, JSON.stringify({ province, cities }));
    } catch {
      /* storage unavailable */
    }
  }, [province, cities]);

  function pickProvince(p: string) {
    setProvince(p);
    setCities([]);
    setFilter("");
  }

  function toggle(c: string) {
    setCities((cs) => (cs.includes(c) ? cs.filter((x) => x !== c) : [...cs, c]));
  }

  const allShownChecked = shown.length > 0 && shown.every((c) => cities.includes(c));
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
          <span>Province</span>
          <select value={province} onChange={(e) => pickProvince(e.target.value)}>
            {PROVINCES.map((p) => (
              <option key={p.province} value={p.province}>
                {p.province}
              </option>
            ))}
          </select>
        </label>

        <fieldset className="cities">
          <legend>
            Cities / municipalities <span className="muted">({cities.length} selected)</span>
          </legend>
          <div className="cities-tools">
            {provinceCities.length > 12 && (
              <input
                type="search"
                placeholder="Filter towns…"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              />
            )}
            <button
              type="button"
              className="btn btn-small"
              onClick={() =>
                setCities((cs) =>
                  allShownChecked ? cs.filter((c) => !shown.includes(c)) : [...new Set([...cs, ...shown])],
                )
              }
            >
              {allShownChecked ? "Clear" : "Select all"}
            </button>
          </div>
          <div className="city-grid">
            {shown.map((c) => (
              <label key={c} className={`city ${cities.includes(c) ? "checked" : ""}`}>
                <input type="checkbox" checked={cities.includes(c)} onChange={() => toggle(c)} />
                <span>{c}</span>
              </label>
            ))}
          </div>
          {cities.length > 8 && (
            <small className="muted">
              Many towns take longer: each one is looked up separately (about 1 second each).
            </small>
          )}
        </fieldset>

        <label>
          <span>
            Other places <span className="muted">(optional)</span>
          </span>
          <input
            value={extra}
            onChange={(e) => setExtra(e.target.value)}
            placeholder="e.g. a barangay or area: Cubao, BGC, Lolomboy"
          />
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
            Will search {queries.length} place{queries.length === 1 ? "" : "s"} for “{kind.trim()}”.
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
