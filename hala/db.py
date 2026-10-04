"""SQLite storage for leads and settings. One file, no server to run."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# On Vercel only /tmp is writable, and it is wiped between cold starts: data there
# is NOT durable. Point HALA_DB at persistent storage for a real deployment.
_FALLBACK = Path("/tmp/hala.db") if os.environ.get("VERCEL") else Path.home() / ".hala" / "hala.db"
DEFAULT_PATH = Path(os.environ.get("HALA_DB", _FALLBACK))

STATUSES = ("new", "contacted", "replied", "meeting", "won", "lost", "skip")

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    website TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    maps_url TEXT NOT NULL DEFAULT '',
    facebook_search TEXT NOT NULL DEFAULT '',
    reviews TEXT NOT NULL DEFAULT '',
    rating TEXT NOT NULL DEFAULT '',
    has_website INTEGER NOT NULL DEFAULT 0,
    reachable INTEGER,
    site_score INTEGER,
    tier TEXT NOT NULL DEFAULT '',
    qual_score INTEGER,
    reasons TEXT NOT NULL DEFAULT '',
    top_issue TEXT NOT NULL DEFAULT '',
    findings TEXT NOT NULL DEFAULT '[]',
    report_html TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    angle TEXT NOT NULL DEFAULT '',
    pitch_source TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    notes TEXT NOT NULL DEFAULT '',
    search_query TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Fields refreshed by a new search or re-audit. Status, notes and anything the
# user has worked on are never overwritten.
DATA_FIELDS = ("name", "email", "website", "phone", "category", "city", "address", "maps_url",
               "facebook_search", "reviews", "rating", "has_website", "reachable", "site_score",
               "tier", "qual_score", "reasons", "top_issue", "findings", "report_html",
               "search_query")
PITCH_FIELDS = ("subject", "body", "angle", "pitch_source", "message")
EDITABLE_FIELDS = ("status", "notes", "subject", "body", "message", "email", "phone")

SETTING_KEYS = ("sender_name", "sender_company", "sender_email", "sender_address",
                "report_base_url", "google_api_key", "anthropic_api_key", "use_ai")
SECRET_KEYS = ("google_api_key", "anthropic_api_key")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def lead_key(name: str, address: str, website: str = "") -> str:
    return "|".join(x.strip().lower() for x in (name, address or website))


class Store:
    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    @contextmanager
    def _tx(self):
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # --- leads -------------------------------------------------------------

    def upsert_lead(self, data: dict) -> int:
        """Insert or refresh a lead. Returns its id."""
        key = data.get("key") or lead_key(data.get("name", ""), data.get("address", ""),
                                          data.get("website", ""))
        row = {k: data[k] for k in DATA_FIELDS + PITCH_FIELDS if k in data}
        if isinstance(row.get("findings"), list):
            row["findings"] = json.dumps(row["findings"])
        now = _now()
        with self._tx() as c:
            existing = c.execute("SELECT id, status FROM leads WHERE key = ?", (key,)).fetchone()
            if existing is None:
                cols = ["key", "created_at", "updated_at", *row]
                c.execute(f"INSERT INTO leads ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                          [key, now, now, *row.values()])
                return c.execute("SELECT last_insert_rowid()").fetchone()[0]
            if existing["status"] != "new":
                # The user is already working this lead: keep their copy.
                row = {k: v for k, v in row.items() if k not in PITCH_FIELDS}
            sets = ", ".join(f"{k} = ?" for k in row)
            c.execute(f"UPDATE leads SET {sets}, updated_at = ? WHERE id = ?",
                      [*row.values(), now, existing["id"]])
            return existing["id"]

    def get_lead(self, lead_id: int, with_report: bool = False) -> dict | None:
        with self._tx() as c:
            r = c.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return self._row(r, with_report) if r else None

    def list_leads(self, has_website: bool | None = None, status: str | None = None,
                   q: str | None = None) -> list[dict]:
        where, args = [], []
        if has_website is not None:
            where.append("has_website = ?")
            args.append(int(has_website))
        if status:
            where.append("status = ?")
            args.append(status)
        if q:
            where.append("(name LIKE ? OR city LIKE ? OR category LIKE ? OR email LIKE ?)")
            args.extend([f"%{q}%"] * 4)
        sql = "SELECT * FROM leads"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY (qual_score IS NULL), qual_score DESC, id DESC"
        with self._tx() as c:
            return [self._row(r) for r in c.execute(sql, args).fetchall()]

    def update_lead(self, lead_id: int, changes: dict) -> dict | None:
        changes = {k: v for k, v in changes.items() if k in EDITABLE_FIELDS}
        if "status" in changes and changes["status"] not in STATUSES:
            raise ValueError(f"unknown status {changes['status']!r}")
        if changes:
            sets = ", ".join(f"{k} = ?" for k in changes)
            with self._tx() as c:
                c.execute(f"UPDATE leads SET {sets}, updated_at = ? WHERE id = ?",
                          [*changes.values(), _now(), lead_id])
        return self.get_lead(lead_id)

    def delete_lead(self, lead_id: int) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM leads WHERE id = ?", (lead_id,))

    def stats(self) -> dict:
        with self._tx() as c:
            by_status = dict(c.execute("SELECT status, COUNT(*) FROM leads GROUP BY status").fetchall())
            total, with_site, no_site, tier_a = c.execute(
                "SELECT COUNT(*), SUM(has_website = 1), SUM(has_website = 0), "
                "SUM(tier = 'A') FROM leads").fetchone()
            angles = c.execute(
                "SELECT angle, COUNT(*) AS sent, "
                "SUM(status IN ('replied', 'meeting', 'won')) AS replies "
                "FROM leads WHERE status NOT IN ('new', 'skip') AND angle != '' "
                "GROUP BY angle ORDER BY sent DESC").fetchall()
        return {
            "total": total or 0, "with_website": with_site or 0, "no_website": no_site or 0,
            "tier_a": tier_a or 0,
            "by_status": {s: by_status.get(s, 0) for s in STATUSES},
            "angles": [dict(a) for a in angles],
        }

    @staticmethod
    def _row(r: sqlite3.Row, with_report: bool = False) -> dict:
        d = dict(r)
        d["findings"] = json.loads(d.get("findings") or "[]")
        d["has_website"] = bool(d["has_website"])
        if d.get("reachable") is not None:
            d["reachable"] = bool(d["reachable"])
        if not with_report:
            d.pop("report_html", None)
        return d

    # --- settings ----------------------------------------------------------

    def get_settings(self) -> dict:
        with self._tx() as c:
            stored = dict(c.execute("SELECT key, value FROM settings").fetchall())
        env = {
            "sender_name": os.environ.get("HALA_SENDER_NAME", ""),
            "sender_company": os.environ.get("HALA_SENDER_COMPANY", ""),
            "sender_email": os.environ.get("HALA_SENDER_EMAIL", ""),
            "sender_address": os.environ.get("HALA_SENDER_ADDRESS", ""),
            "report_base_url": os.environ.get("HALA_REPORT_BASE_URL", ""),
            "google_api_key": os.environ.get("GOOGLE_MAPS_API_KEY", ""),
            "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
            "use_ai": "1",
        }
        return {k: stored.get(k) or env.get(k, "") for k in SETTING_KEYS}

    def save_settings(self, values: dict) -> None:
        with self._tx() as c:
            for k, v in values.items():
                if k in SETTING_KEYS and v is not None:
                    c.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                              "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, str(v)))

    def sender(self) -> dict:
        s = self.get_settings()
        return {"name": s["sender_name"], "company": s["sender_company"],
                "email": s["sender_email"], "address": s["sender_address"]}
