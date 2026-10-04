"""Storage for leads, settings and search jobs.

Two backends behind one class:
- SQLite (default): one local file, nothing to set up. Used by `hala serve`.
- Postgres (when DATABASE_URL is set, e.g. Supabase): needed on Vercel, where
  the filesystem is temporary and every request may hit a different instance.

On Postgres the tables live in their own `hala` schema with row level security
enabled, so Supabase's public REST API (which uses the anon key that ships to
browsers) cannot read them. Only the server's direct database connection can.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_PATH = Path(os.environ.get("HALA_DB", Path.home() / ".hala" / "hala.db"))

STATUSES = ("new", "contacted", "replied", "meeting", "won", "lost", "skip")
FOLLOW_UP_DAYS = 3  # contacted this long ago with no reply -> follow up

# (name, type) for every lead column except the id. New columns added here are
# created automatically on existing databases at startup.
LEAD_COLUMNS = [
    ("key", "TEXT NOT NULL"),
    ("name", "TEXT NOT NULL DEFAULT ''"),
    ("email", "TEXT NOT NULL DEFAULT ''"),
    ("website", "TEXT NOT NULL DEFAULT ''"),
    ("phone", "TEXT NOT NULL DEFAULT ''"),
    ("category", "TEXT NOT NULL DEFAULT ''"),
    ("city", "TEXT NOT NULL DEFAULT ''"),
    ("address", "TEXT NOT NULL DEFAULT ''"),
    ("maps_url", "TEXT NOT NULL DEFAULT ''"),
    ("facebook_search", "TEXT NOT NULL DEFAULT ''"),
    ("reviews", "TEXT NOT NULL DEFAULT ''"),
    ("rating", "TEXT NOT NULL DEFAULT ''"),
    ("has_website", "INTEGER NOT NULL DEFAULT 0"),
    ("reachable", "INTEGER"),
    ("site_score", "INTEGER"),
    ("tier", "TEXT NOT NULL DEFAULT ''"),
    ("qual_score", "INTEGER"),
    ("reasons", "TEXT NOT NULL DEFAULT ''"),
    ("top_issue", "TEXT NOT NULL DEFAULT ''"),
    ("findings", "TEXT NOT NULL DEFAULT '[]'"),
    ("report_html", "TEXT NOT NULL DEFAULT ''"),
    ("report_token", "TEXT NOT NULL DEFAULT ''"),
    ("preview_html", "TEXT NOT NULL DEFAULT ''"),
    ("preview_token", "TEXT NOT NULL DEFAULT ''"),
    ("preview_notes", "TEXT NOT NULL DEFAULT ''"),
    ("preview_source", "TEXT NOT NULL DEFAULT ''"),
    ("subject", "TEXT NOT NULL DEFAULT ''"),
    ("body", "TEXT NOT NULL DEFAULT ''"),
    ("angle", "TEXT NOT NULL DEFAULT ''"),
    ("pitch_source", "TEXT NOT NULL DEFAULT ''"),
    ("message", "TEXT NOT NULL DEFAULT ''"),
    ("status", "TEXT NOT NULL DEFAULT 'new'"),
    ("contacted_at", "TEXT NOT NULL DEFAULT ''"),
    ("notes", "TEXT NOT NULL DEFAULT ''"),
    ("search_query", "TEXT NOT NULL DEFAULT ''"),
    ("created_at", "TEXT NOT NULL DEFAULT ''"),
    ("updated_at", "TEXT NOT NULL DEFAULT ''"),
]

JOB_COLUMNS = [
    ("status", "TEXT NOT NULL DEFAULT 'queued'"),   # queued | running | done | error
    ("stage", "TEXT NOT NULL DEFAULT ''"),
    ("done", "INTEGER NOT NULL DEFAULT 0"),
    ("total", "INTEGER NOT NULL DEFAULT 0"),
    ("error", "TEXT"),
    ("with_website", "INTEGER NOT NULL DEFAULT 0"),
    ("no_website", "INTEGER NOT NULL DEFAULT 0"),
    ("request", "TEXT NOT NULL DEFAULT '{}'"),
    ("pending", "TEXT NOT NULL DEFAULT '[]'"),
    ("lease_until", "TEXT NOT NULL DEFAULT ''"),
    ("created_at", "TEXT NOT NULL DEFAULT ''"),
    ("updated_at", "TEXT NOT NULL DEFAULT ''"),
]
PUBLIC_JOB_FIELDS = ("id", "status", "stage", "done", "total", "error", "with_website", "no_website")

# Fields refreshed by a new search or re-audit. Status, notes and anything the
# user has worked on are never overwritten.
DATA_FIELDS = ("name", "email", "website", "phone", "category", "city", "address", "maps_url",
               "facebook_search", "reviews", "rating", "has_website", "reachable", "site_score",
               "tier", "qual_score", "reasons", "top_issue", "findings", "report_html",
               "search_query")
PITCH_FIELDS = ("subject", "body", "angle", "pitch_source", "message")
EDITABLE_FIELDS = ("status", "notes", "subject", "body", "message", "email", "phone")

AI_KEY_SETTINGS = ("anthropic_api_key", "gemini_api_key", "groq_api_key", "openrouter_api_key",
                   "openai_api_key", "custom_api_key")
SETTING_KEYS = ("sender_name", "sender_company", "sender_email", "sender_address",
                "report_base_url", "google_api_key", "use_ai", "ai_provider", "ai_model",
                "ai_base_url", *AI_KEY_SETTINGS)
SECRET_KEYS = ("google_api_key", *AI_KEY_SETTINGS)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def lead_key(name: str, address: str, website: str = "") -> str:
    return "|".join(x.strip().lower() for x in (name, address or website))


class DatabaseUnavailable(RuntimeError):
    """The database can't be reached. The message says what to fix (never contains secrets)."""


def _explain(err: Exception, pg: bool, target: str = "") -> str:
    text = str(err).lower()
    if "[your-password]" in target.lower():
        return ("DATABASE_URL still contains [YOUR-PASSWORD]. Replace it (including the brackets) "
                "with your Supabase database password.")
    if not pg:
        return f"Couldn't open the local database file ({err})."
    if "password authentication failed" in text or "[your-password]" in text:
        return ("Supabase rejected the database password. Check the password inside DATABASE_URL "
                "(replace [YOUR-PASSWORD] with your real database password).")
    if "network is unreachable" in text or "cannot assign requested address" in text or (
            "db." in text and ".supabase.co" in text):
        return ("Can't reach Supabase's direct database address (it's IPv6-only, which Vercel "
                "doesn't support). Use the Transaction pooler connection string instead "
                "(host ...pooler.supabase.com, port 6543).")
    if "tenant or user not found" in text:
        return ("Supabase's pooler doesn't recognise the user. In the pooler connection string the "
                "user looks like postgres.<project-ref>, copy it again from Supabase → Connect.")
    if "timeout" in text or "timed out" in text:
        return "Timed out connecting to the database. Check the host and port in DATABASE_URL."
    if "could not translate host name" in text or "name or service not known" in text:
        return "The database host name in DATABASE_URL doesn't exist. Copy it again from Supabase."
    reason = (str(err).strip().splitlines() or [type(err).__name__])[0][:200]
    try:
        password = urlparse(target).password if target else None
    except ValueError:
        password = None
    if password:
        reason = reason.replace(password, "***")
    return f"Couldn't connect to the database ({reason}). Check DATABASE_URL."


def _is_postgres(target: str) -> bool:
    return target.startswith(("postgres://", "postgresql://"))


class Store:
    def __init__(self, target: str | Path | None = None):
        target = str(target or os.environ.get("DATABASE_URL") or DEFAULT_PATH)
        self.target = target
        self.pg = _is_postgres(target)
        self.path = "postgres" if self.pg else target
        self._lock = threading.Lock()
        self._conn = None
        prefix = "hala." if self.pg else ""
        self.leads, self.settings_t, self.jobs = (f"{prefix}leads", f"{prefix}settings",
                                                  f"{prefix}jobs")
        self._ready = False  # connect + create tables lazily, on first use

    @property
    def configured(self) -> bool:
        """False on Vercel without DATABASE_URL (the filesystem there is temporary)."""
        return self.pg or not os.environ.get("VERCEL")

    def check(self) -> None:
        """Connect now; raises DatabaseUnavailable with a readable reason."""
        with self._tx() as run:
            run("SELECT 1")

    # --- connection --------------------------------------------------------

    def _connect(self):
        if not self.configured:
            raise DatabaseUnavailable("DATABASE_URL isn't set. Add your Supabase Transaction pooler "
                                      "connection string in Vercel → Settings → Environment Variables.")
        if not self.pg and self.target != ":memory:":
            Path(self.target).parent.mkdir(parents=True, exist_ok=True)
        if self.pg:
            import psycopg
            from psycopg.rows import dict_row
            # prepare_threshold=None: Supabase's pooler (transaction mode) can't
            # keep prepared statements between transactions.
            return psycopg.connect(self.target, row_factory=dict_row, prepare_threshold=None,
                                   connect_timeout=10)
        conn = sqlite3.connect(self.target, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _tx(self):
        """Yield an `exec(sql, args)` function; SQL uses `?` placeholders on both backends."""
        with self._lock:
            if self._conn is None or (self.pg and (self._conn.closed or self._conn.broken)):
                try:
                    self._conn = self._connect()
                except DatabaseUnavailable:
                    raise
                except Exception as e:
                    raise DatabaseUnavailable(_explain(e, self.pg, self.target)) from e
            conn = self._conn

            def run(sql: str, args=()):
                if self.pg:
                    sql = sql.replace("?", "%s")
                cur = conn.cursor()
                cur.execute(sql, tuple(args))
                return cur

            if not self._ready:
                try:
                    self._migrate(run)
                    conn.commit()
                    self._ready = True
                except Exception as e:
                    try:
                        conn.rollback()
                    except Exception:
                        self._conn = None
                    raise DatabaseUnavailable(
                        f"Connected, but couldn't set up Hala's tables: {e}") from e

            try:
                yield run
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    self._conn = None  # connection is gone; reconnect next time
                raise

    def _migrate(self, run) -> None:
        id_col = ("id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY" if self.pg
                  else "id INTEGER PRIMARY KEY AUTOINCREMENT")
        cols = lambda spec: ", ".join(f"{n} {t}" for n, t in spec)  # noqa: E731
        if self.pg:
            run("CREATE SCHEMA IF NOT EXISTS hala")
        run(f"CREATE TABLE IF NOT EXISTS {self.leads} ({id_col}, {cols(LEAD_COLUMNS)})")
        run(f"CREATE TABLE IF NOT EXISTS {self.settings_t} (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        run(f"CREATE TABLE IF NOT EXISTS {self.jobs} (id TEXT PRIMARY KEY, {cols(JOB_COLUMNS)})")
        for table, spec in ((self.leads, LEAD_COLUMNS), (self.jobs, JOB_COLUMNS)):
            have = self._columns(run, table)
            for name, typ in spec:
                if name not in have:
                    run(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
        run(f"CREATE UNIQUE INDEX IF NOT EXISTS leads_key_idx ON {self.leads} (key)")
        run(f"CREATE INDEX IF NOT EXISTS leads_token_idx ON {self.leads} (report_token)")
        run(f"CREATE INDEX IF NOT EXISTS leads_preview_idx ON {self.leads} (preview_token)")
        if self.pg:
            for t in (self.leads, self.settings_t, self.jobs):
                run(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        missing = run(f"SELECT id FROM {self.leads} WHERE report_token = ''").fetchall()
        for r in missing:
            run(f"UPDATE {self.leads} SET report_token = ? WHERE id = ?",
                (secrets.token_urlsafe(12), r["id"]))

    def _columns(self, run, table: str) -> set[str]:
        if self.pg:
            schema, name = table.split(".")
            rows = run("SELECT column_name FROM information_schema.columns "
                       "WHERE table_schema = ? AND table_name = ?", (schema, name)).fetchall()
            return {r["column_name"] for r in rows}
        return {r["name"] for r in run(f"PRAGMA table_info({table})").fetchall()}

    # --- leads -------------------------------------------------------------

    def upsert_lead(self, data: dict, force_pitch: bool = False) -> int:
        """Insert or refresh a lead. Returns its id. The pitch is only overwritten for
        leads still marked 'new', unless force_pitch (an explicit re-audit)."""
        key = data.get("key") or lead_key(data.get("name", ""), data.get("address", ""),
                                          data.get("website", ""))
        row = {k: data[k] for k in DATA_FIELDS + PITCH_FIELDS if k in data}
        if isinstance(row.get("findings"), list):
            row["findings"] = json.dumps(row["findings"])
        now = _now()
        with self._tx() as run:
            existing = run(f"SELECT id, status FROM {self.leads} WHERE key = ?", (key,)).fetchone()
            if existing is None:
                cols = ["key", "report_token", "created_at", "updated_at", *row]
                values = [key, secrets.token_urlsafe(12), now, now, *row.values()]
                cur = run(f"INSERT INTO {self.leads} ({', '.join(cols)}) "
                          f"VALUES ({', '.join('?' * len(cols))}) RETURNING id", values)
                return cur.fetchone()["id"]
            if existing["status"] != "new" and not force_pitch:
                # The user is already working this lead: keep their copy.
                row = {k: v for k, v in row.items() if k not in PITCH_FIELDS}
            sets = ", ".join(f"{k} = ?" for k in row)
            run(f"UPDATE {self.leads} SET {sets}, updated_at = ? WHERE id = ?",
                [*row.values(), now, existing["id"]])
            return existing["id"]

    def get_lead(self, lead_id: int, with_report: bool = False) -> dict | None:
        with self._tx() as run:
            r = run(f"SELECT * FROM {self.leads} WHERE id = ?", (lead_id,)).fetchone()
        return self._row(r, with_report) if r else None

    def get_lead_by_token(self, token: str) -> dict | None:
        if not token:
            return None
        with self._tx() as run:
            r = run(f"SELECT * FROM {self.leads} WHERE report_token = ?", (token,)).fetchone()
        return self._row(r, True) if r else None

    def save_preview(self, lead_id: int, html: str, notes: str, source: str) -> dict | None:
        """Store a generated preview. The link (token) stays the same when regenerated."""
        with self._tx() as run:
            r = run(f"SELECT preview_token FROM {self.leads} WHERE id = ?", (lead_id,)).fetchone()
            if r is None:
                return None
            token = r["preview_token"] or secrets.token_urlsafe(12)
            run(f"UPDATE {self.leads} SET preview_html = ?, preview_token = ?, preview_notes = ?, "
                f"preview_source = ?, updated_at = ? WHERE id = ?",
                (html, token, notes, source, _now(), lead_id))
        return self.get_lead(lead_id)

    def get_preview(self, token: str) -> str | None:
        if not token:
            return None
        with self._tx() as run:
            r = run(f"SELECT preview_html FROM {self.leads} WHERE preview_token = ?", (token,)).fetchone()
        return r["preview_html"] if r and r["preview_html"] else None

    def list_leads(self, has_website: bool | None = None, status: str | None = None,
                   q: str | None = None) -> list[dict]:
        where, args = [], []
        if has_website is not None:
            where.append("has_website = ?")
            args.append(int(has_website))
        if status == "followup":
            where.append("status = 'contacted' AND contacted_at != '' AND contacted_at < ?")
            args.append(self._follow_up_cutoff())
        elif status:
            where.append("status = ?")
            args.append(status)
        if q:
            where.append("(LOWER(name) LIKE ? OR LOWER(city) LIKE ? OR LOWER(category) LIKE ? "
                         "OR LOWER(email) LIKE ?)")
            args.extend([f"%{q.lower()}%"] * 4)
        cols = ", ".join(["id"] + [n for n, _ in LEAD_COLUMNS if n not in ("report_html", "preview_html")])
        sql = f"SELECT {cols} FROM {self.leads}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY (qual_score IS NULL), qual_score DESC, id DESC"
        with self._tx() as run:
            return [self._row(r) for r in run(sql, args).fetchall()]

    def update_lead(self, lead_id: int, changes: dict) -> dict | None:
        changes = {k: v for k, v in changes.items() if k in EDITABLE_FIELDS}
        if "status" in changes and changes["status"] not in STATUSES:
            raise ValueError(f"unknown status {changes['status']!r}")
        if changes:
            with self._tx() as run:
                if "status" in changes:
                    prev = run(f"SELECT status FROM {self.leads} WHERE id = ?", (lead_id,)).fetchone()
                    if changes["status"] == "contacted" and prev and prev["status"] != "contacted":
                        changes["contacted_at"] = _now()
                    elif changes["status"] == "new":
                        changes["contacted_at"] = ""
                sets = ", ".join(f"{k} = ?" for k in changes)
                run(f"UPDATE {self.leads} SET {sets}, updated_at = ? WHERE id = ?",
                    [*changes.values(), _now(), lead_id])
        return self.get_lead(lead_id)

    @staticmethod
    def _follow_up_cutoff() -> str:
        return (datetime.now(timezone.utc) - timedelta(days=FOLLOW_UP_DAYS)).isoformat(timespec="seconds")

    def delete_lead(self, lead_id: int) -> None:
        with self._tx() as run:
            run(f"DELETE FROM {self.leads} WHERE id = ?", (lead_id,))

    def stats(self) -> dict:
        with self._tx() as run:
            by_status = {r["status"]: r["n"] for r in run(
                f"SELECT status, COUNT(*) AS n FROM {self.leads} GROUP BY status").fetchall()}
            t = run(f"""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN has_website = 1 THEN 1 ELSE 0 END) AS with_site,
                       SUM(CASE WHEN has_website = 0 THEN 1 ELSE 0 END) AS no_site,
                       SUM(CASE WHEN tier = 'A' THEN 1 ELSE 0 END) AS tier_a,
                       SUM(CASE WHEN status = 'contacted' AND contacted_at != ''
                                 AND contacted_at < ? THEN 1 ELSE 0 END) AS follow_ups
                FROM {self.leads}""", (self._follow_up_cutoff(),)).fetchone()
            angles = run(f"""
                SELECT angle, COUNT(*) AS sent,
                       SUM(CASE WHEN status IN ('replied', 'meeting', 'won') THEN 1 ELSE 0 END) AS replies
                FROM {self.leads}
                WHERE status NOT IN ('new', 'skip') AND angle != ''
                GROUP BY angle ORDER BY sent DESC""").fetchall()
        return {
            "total": int(t["total"] or 0), "with_website": int(t["with_site"] or 0),
            "no_website": int(t["no_site"] or 0), "tier_a": int(t["tier_a"] or 0),
            "follow_ups_due": int(t["follow_ups"] or 0),
            "by_status": {s: int(by_status.get(s, 0)) for s in STATUSES},
            "angles": [{"angle": a["angle"], "sent": int(a["sent"]), "replies": int(a["replies"] or 0)}
                       for a in angles],
        }

    @staticmethod
    def _row(r, with_report: bool = False) -> dict:
        d = dict(r)
        d["findings"] = json.loads(d.get("findings") or "[]")
        d["has_website"] = bool(d["has_website"])
        if d.get("reachable") is not None:
            d["reachable"] = bool(d["reachable"])
        if not with_report:
            d.pop("report_html", None)
            d.pop("preview_html", None)
        return d

    # --- jobs --------------------------------------------------------------

    def create_job(self, request: dict) -> dict:
        job_id = secrets.token_hex(8)
        now = _now()
        with self._tx() as run:
            run(f"INSERT INTO {self.jobs} (id, status, stage, request, created_at, updated_at) "
                f"VALUES (?, 'queued', 'Starting', ?, ?, ?)", (job_id, json.dumps(request), now, now))
        return self.get_job(job_id)

    def get_job(self, job_id: str, internal: bool = False) -> dict | None:
        with self._tx() as run:
            r = run(f"SELECT * FROM {self.jobs} WHERE id = ?", (job_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        if internal:
            d["request"] = json.loads(d["request"])
            d["pending"] = json.loads(d["pending"])
            return d
        return {k: d[k] for k in PUBLIC_JOB_FIELDS}

    def update_job(self, job_id: str, **fields) -> None:
        if "pending" in fields:
            fields["pending"] = json.dumps(fields["pending"])
        fields["updated_at"] = _now()
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._tx() as run:
            run(f"UPDATE {self.jobs} SET {sets} WHERE id = ?", [*fields.values(), job_id])

    def claim_job(self, job_id: str, seconds: int) -> bool:
        """Take a short lease so two browser tabs can't process the same job at once."""
        now = datetime.now(timezone.utc)
        until = (now + timedelta(seconds=seconds)).isoformat(timespec="seconds")
        with self._tx() as run:
            cur = run(f"UPDATE {self.jobs} SET lease_until = ? WHERE id = ? "
                      f"AND (lease_until = '' OR lease_until < ?)",
                      (until, job_id, now.isoformat(timespec="seconds")))
            return cur.rowcount == 1

    def release_job(self, job_id: str) -> None:
        with self._tx() as run:
            run(f"UPDATE {self.jobs} SET lease_until = '' WHERE id = ?", (job_id,))

    # --- settings ----------------------------------------------------------

    def get_settings(self) -> dict:
        with self._tx() as run:
            stored = {r["key"]: r["value"] for r in
                      run(f"SELECT key, value FROM {self.settings_t}").fetchall()}
        env = {
            "sender_name": os.environ.get("HALA_SENDER_NAME", ""),
            "sender_company": os.environ.get("HALA_SENDER_COMPANY", ""),
            "sender_email": os.environ.get("HALA_SENDER_EMAIL", ""),
            "sender_address": os.environ.get("HALA_SENDER_ADDRESS", ""),
            "report_base_url": os.environ.get("HALA_REPORT_BASE_URL", ""),
            "google_api_key": os.environ.get("GOOGLE_MAPS_API_KEY", ""),
            "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
            "gemini_api_key": os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", ""),
            "groq_api_key": os.environ.get("GROQ_API_KEY", ""),
            "openrouter_api_key": os.environ.get("OPENROUTER_API_KEY", ""),
            "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
            "custom_api_key": os.environ.get("HALA_AI_API_KEY", ""),
            "ai_provider": os.environ.get("HALA_AI_PROVIDER", ""),
            "ai_model": os.environ.get("HALA_AI_MODEL", ""),
            "ai_base_url": os.environ.get("HALA_AI_BASE_URL", ""),
            "use_ai": "1",
        }
        out = {k: stored.get(k) or env.get(k, "") for k in SETTING_KEYS}
        if not out["ai_provider"]:
            # Default to whichever provider has a key, preferring Claude.
            with_key = [k[: -len("_api_key")] for k in AI_KEY_SETTINGS if out[k]]
            out["ai_provider"] = with_key[0] if with_key else "anthropic"
        return out

    def save_settings(self, values: dict) -> None:
        with self._tx() as run:
            for k, v in values.items():
                if k in SETTING_KEYS and v is not None:
                    run(f"INSERT INTO {self.settings_t} (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, str(v)))

    def sender(self) -> dict:
        s = self.get_settings()
        return {"name": s["sender_name"], "company": s["sender_company"],
                "email": s["sender_email"], "address": s["sender_address"]}
