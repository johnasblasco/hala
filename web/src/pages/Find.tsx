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
  const alive = useRef(true);
  const looping = useRef<string | null>(null);

  useEffect(() => {
    alive.current = true;
    api.settings().then(setSettings).catch(() => undefined);
    // Pick up a search that was still running when you left this page.
    const saved = readActiveJob();
    if (saved) {
      api
        .job(saved)
        .then((j) => {
          // Only pick up a search that is still alive and recent; otherwise forget it.
          const recent = j.updated_at && Date.now() - new Date(j.updated_at).getTime() < 10 * 60_000;
          if ((j.status === "queued" || j.status === "running") && recent) {
            setJob(j);
            drive(j.id);
          } else {
            clearActiveJob();
          }
        })
        .catch(clearActiveJob);
    }
    return () => {
      alive.current = false;
      looping.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Advance the job step by step until it finishes. Each step is one short request. */
  async function drive(id: string) {
    if (looping.current === id) return;
    looping.current = id;
    setError(null);
    // While a long step runs (the search itself), show its live stage text.
    const poll = window.setInterval(() => {
      api.job(id).then((j) => alive.current && looping.current === id && setJob(j)).catch(() => undefined);
    }, 2500);
    let failures = 0;
    try {
      while (alive.current && looping.current === id) {
        try {
          const next = await api.stepJob(id);
          failures = 0;
          if (!alive.current) return;
          setJob(next);
          if (next.status === "done" || next.status === "error") {
            clearActiveJob();
            return;
          }
        } catch (err) {
          if (++failures >= 3) {
            setError(`${(err as Error).message}. Your progress is saved, so click Resume to continue.`);
            return;
          }
          await new Promise((r) => setTimeout(r, 2000 * failures));
        }
      }
    } finally {
      window.clearInterval(poll);
      if (looping.current === id) looping.current = null;
    }
  }

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
  const running = job?.status === "running" || job?.status === "queued";

  async function cancel() {
    if (!job) return;
    looping.current = null; // stop driving it
    clearActiveJob();
    try {
      setJob(await api.cancelJob(job.id));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function start(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const j = await api.search(queries, source);
      setJob(j);
      saveActiveJob(j.id);
      drive(j.id);
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
        {error && job && running && (
          <div>
            <button type="button" className="btn" onClick={() => drive(job.id)}>
              Resume
            </button>
          </div>
        )}
      </form>

      {job && (
        <section className="card">
          <h2>{job.status === "done"
              ? "Done"
              : job.stage === "Cancelled"
                ? "Search cancelled"
                : job.status === "error"
                  ? "Something went wrong"
                  : job.stage}</h2>
          {running && (
            <>
              <div className="progress">
                <div className="progress-bar" style={{ width: `${job.total ? pct : 8}%` }} />
              </div>
              <div className="row-between">
                <p className="muted small">
                  {job.total ? `Audited ${job.done} of ${job.total} websites` : "This can take a minute or two…"}
                </p>
                <button type="button" className="btn btn-small" onClick={cancel}>
                  Cancel search
                </button>
              </div>
            </>
          )}
          {job.status === "error" && job.stage !== "Cancelled" && <ErrorBox error={job.error} />}
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

const JOB_KEY = "hala.find.job";

function readActiveJob(): string | null {
  try {
    return localStorage.getItem(JOB_KEY);
  } catch {
    return null;
  }
}

function saveActiveJob(id: string) {
  try {
    localStorage.setItem(JOB_KEY, id);
  } catch {
    /* storage unavailable */
  }
}

function clearActiveJob() {
  try {
    localStorage.removeItem(JOB_KEY);
  } catch {
    /* storage unavailable */
  }
}
