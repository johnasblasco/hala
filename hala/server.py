"""Web API (and, locally, the static UI) for Hala.

    hala serve            # http://localhost:8000

Works the same locally and on Vercel:
- Storage: SQLite locally, Postgres (Supabase) when DATABASE_URL is set.
- Searches run as small steps the browser drives (POST /api/jobs/{id}/step),
  because serverless functions stop as soon as they return a response.
- Login: when SUPABASE_URL is set, every /api route needs a Supabase session
  from an allowed email. Report pages stay public (they're linked in emails)
  but are addressed by an unguessable token.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import threading
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import find as finder
from .audit import audit
from .db import SECRET_KEYS, STATUSES, DatabaseUnavailable, Store
from .pitch import no_website_message, write_pitch
from .qualify import qualify
from .report import render_report, slugify

STATIC_DIR = Path(__file__).parent / "static"
STEP_BATCH = 4          # websites audited per step request
STEP_LEASE_SECONDS = 290


def public_base_url(default: str = "http://localhost:8000") -> str:
    """Base URL used in links that leave the app (report links inside emails).

    HALA_PUBLIC_URL wins; on Vercel fall back to the production domain, then the
    deployment URL. Locally it's the `hala serve` address.
    """
    explicit = os.environ.get("HALA_PUBLIC_URL", "").rstrip("/")
    if explicit:
        return explicit
    for var in ("VERCEL_PROJECT_PRODUCTION_URL", "VERCEL_URL"):
        host = os.environ.get(var, "").strip()
        if host:
            return f"https://{host}"
    return default


# --- auth ------------------------------------------------------------------

def auth_config() -> dict | None:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_PUBLISHABLE_KEY") or ""
    if url and key:
        return {"url": url, "anon_key": key}
    return None


def allowed_emails() -> set[str]:
    raw = os.environ.get("HALA_ALLOWED_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


_token_cache: dict[str, tuple[str, float]] = {}
_token_lock = threading.Lock()


def verify_token(token: str, cfg: dict) -> str | None:
    """Ask Supabase who this access token belongs to. Returns the email, or None.

    Works with both legacy (HS256) and new asymmetric Supabase signing keys,
    since Supabase does the verification. Results are cached for 5 minutes.
    """
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    with _token_lock:
        hit = _token_cache.get(digest)
        if hit and hit[1] > now:
            return hit[0]
    req = urllib.request.Request(f"{cfg['url']}/auth/v1/user", headers={
        "apikey": cfg["anon_key"], "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            email = (json.loads(resp.read()).get("email") or "").lower()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    if email:
        with _token_lock:
            if len(_token_cache) > 1000:
                _token_cache.clear()
            _token_cache[digest] = (email, now + 300)
    return email or None


def require_user(request: Request) -> str | None:
    cfg = auth_config()
    if cfg is None:
        if os.environ.get("VERCEL") and not os.environ.get("HALA_ALLOW_NO_AUTH"):
            raise HTTPException(503, "Login isn't configured. Set SUPABASE_URL, SUPABASE_ANON_KEY "
                                     "and HALA_ALLOWED_EMAILS in Vercel.")
        return None  # local use: no login
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(401, "Please log in.")
    email = verify_token(token, cfg)
    if not email:
        raise HTTPException(401, "Your session expired. Please log in again.")
    allowed = allowed_emails()
    if not allowed:
        raise HTTPException(403, "No one is allowed in yet. Set HALA_ALLOWED_EMAILS in Vercel.")
    if email not in allowed:
        raise HTTPException(403, f"{email} isn't allowed to use this Hala workspace.")
    return email


# --- request bodies --------------------------------------------------------

class SearchRequest(BaseModel):
    queries: list[str]
    source: str = "auto"      # auto | osm | google
    max_per_query: int = 60


class AuditRequest(BaseModel):
    url: str


class LeadPatch(BaseModel):
    status: str | None = None
    notes: str | None = None
    subject: str | None = None
    body: str | None = None
    message: str | None = None
    email: str | None = None
    phone: str | None = None


class SettingsPatch(BaseModel):
    sender_name: str | None = None
    sender_company: str | None = None
    sender_email: str | None = None
    sender_address: str | None = None
    report_base_url: str | None = None
    google_api_key: str | None = None
    anthropic_api_key: str | None = None
    use_ai: str | None = None


# --- pipeline --------------------------------------------------------------

def _claude_client(settings: dict):
    if settings.get("use_ai") != "1" or not settings.get("anthropic_api_key"):
        return None
    import anthropic
    return anthropic.Anthropic(api_key=settings["anthropic_api_key"])


def report_slug(token: str, name: str) -> str:
    return f"{slugify(name)}-{token}"


def report_url(settings: dict, token: str, name: str, local_base: str) -> str:
    base = (settings.get("report_base_url") or "").rstrip("/")
    if base:
        return f"{base}/{report_slug(token, name)}.html"
    return f"{local_base}/reports/{token}"


def process_site_lead(store: Store, lead: dict, settings: dict, client, local_base: str,
                      result=None) -> int:
    """Audit (unless given), qualify, render report and write the pitch for one lead."""
    result = result or audit(lead["website"])
    q = qualify(lead, result)
    data = {
        **lead,
        "has_website": 1,
        "reachable": int(result.reachable),
        "site_score": result.score,
        "tier": q.tier,
        "qual_score": q.score,
        "reasons": "; ".join(q.reasons),
        "top_issue": result.top_finding.id if result.top_finding else "",
        "findings": [asdict(f) for f in result.findings],
    }
    lead_id = store.upsert_lead(data)
    token = store.get_lead(lead_id)["report_token"]
    sender = store.sender()
    report = render_report(lead, result, sender)
    pitch_data: dict = {}
    if q.tier != "skip":
        url = report_url(settings, token, lead.get("name", ""), local_base)
        p = write_pitch(lead, result, url, sender, use_claude=client is not None, client=client)
        pitch_data = {"subject": p.subject, "body": p.body, "angle": p.angle,
                      "pitch_source": p.source}
    store.upsert_lead({**data, "report_html": report, **pitch_data})
    return lead_id


def _search_stage(store: Store, job: dict) -> None:
    """First step: run the business search and queue every website for auditing."""
    req = job["request"]
    settings = store.get_settings()
    source = req.get("source", "auto")
    if source == "auto":
        source = "google" if settings["google_api_key"] else "osm"
    if source == "google":
        if not settings["google_api_key"]:
            raise RuntimeError("Add a Google API key in Settings, or use OpenStreetMap.")
        search = finder.google_search(settings["google_api_key"])
        store.update_job(job["id"], stage="Searching Google Maps")
    else:
        search = finder.osm_search(notify=lambda m: store.update_job(job["id"], stage=m))
    queries = list(dict.fromkeys(q.strip() for q in req.get("queries", []) if q.strip()))
    if not queries:
        raise RuntimeError("Enter at least one search.")

    with_site, no_site = finder.find_leads(queries, search, req.get("max_per_query", 60),
                                           lookup_emails=False)
    label = ", ".join(queries)
    sender = store.sender()
    for lead in no_site:
        store.upsert_lead({**lead, "has_website": 0, "search_query": label,
                           "facebook_search": finder.facebook_search_url(lead),
                           "message": no_website_message(lead, sender)})
    pending = [{**l, "search_query": label} for l in with_site]
    store.update_job(job["id"], status="running" if pending else "done",
                     stage="Auditing websites" if pending else "Done",
                     total=len(pending), with_website=len(with_site),
                     no_website=len(no_site), pending=pending)


def _audit_stage(store: Store, job: dict, local_base: str) -> None:
    """Later steps: find emails for and audit the next few websites."""
    batch, rest = job["pending"][:STEP_BATCH], job["pending"][STEP_BATCH:]

    def prepare(lead: dict):
        if not lead.get("email"):
            lead["email"] = finder.find_email(lead["website"])
        return lead, audit(lead["website"])

    settings = store.get_settings()
    client = _claude_client(settings)
    with ThreadPoolExecutor(max_workers=STEP_BATCH) as pool:
        for lead, result in pool.map(prepare, batch):
            process_site_lead(store, lead, settings, client, local_base, result)
    store.update_job(job["id"], pending=rest, done=job["done"] + len(batch),
                     status="running" if rest else "done",
                     stage="Auditing websites" if rest else "Done")


def step_job(store: Store, job_id: str, local_base: str) -> dict | None:
    """Advance a search job by one step. Safe to call repeatedly and concurrently."""
    job = store.get_job(job_id, internal=True)
    if job is None or job["status"] in ("done", "error"):
        return store.get_job(job_id)
    if not store.claim_job(job_id, STEP_LEASE_SECONDS):
        return store.get_job(job_id)  # another request is already working on it
    try:
        if job["status"] == "queued":
            _search_stage(store, job)
        else:
            _audit_stage(store, job, local_base)
    except Exception as e:  # surfaced to the UI
        store.update_job(job_id, status="error", error=str(e), stage="Failed")
    finally:
        store.release_job(job_id)
    return store.get_job(job_id)


# --- app -------------------------------------------------------------------

def create_app(store: Store | None = None, local_base: str | None = None,
               serve_static: bool = True) -> FastAPI:
    """Build the app. `serve_static=False` when the UI is deployed separately (Vercel)."""
    local_base = local_base or public_base_url()
    store = store or Store()
    app = FastAPI(title="Hala")
    app.state.store = store
    api = APIRouter(prefix="/api", dependencies=[Depends(require_user)])

    @app.exception_handler(DatabaseUnavailable)
    def db_unavailable(_request: Request, exc: DatabaseUnavailable):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.get("/api/health")
    def health():
        """Public setup check: what's configured and whether the database answers.
        Never includes secrets."""
        try:
            store.check()
            database = "ok"
        except DatabaseUnavailable as e:
            database = str(e)
        return {
            "database": database,
            "database_kind": "postgres" if store.pg else "sqlite",
            "login": "on" if auth_config() else "off",
            "allowed_emails": len(allowed_emails()),
            "public_url": public_base_url(),
        }

    @app.get("/api/config")
    def config():
        """Public: tells the UI whether (and how) to show a login screen."""
        cfg = auth_config()
        return {"auth": {"supabase_url": cfg["url"], "anon_key": cfg["anon_key"]} if cfg else None}

    @api.get("/me")
    def me(user: str | None = Depends(require_user)):
        return {"email": user}

    @api.get("/settings")
    def get_settings():
        s = store.get_settings()
        # Never send secrets back to the browser; only whether they are set.
        for k in SECRET_KEYS:
            s[k + "_set"] = bool(s.pop(k))
        return s

    @api.put("/settings")
    def put_settings(patch: SettingsPatch):
        values = patch.model_dump(exclude_none=True)
        for k in SECRET_KEYS:
            if values.get(k) == "":
                values.pop(k)  # blank secret field = keep the existing value
        store.save_settings(values)
        return get_settings()

    @api.delete("/settings/{key}")
    def clear_secret(key: str):
        if key not in SECRET_KEYS:
            raise HTTPException(400, "only API keys can be cleared")
        store.save_settings({key: ""})
        return get_settings()

    @api.post("/search")
    def start_search(req: SearchRequest):
        return store.create_job(req.model_dump())

    @api.post("/jobs/{job_id}/step")
    def advance_job(job_id: str):
        job = step_job(store, job_id, local_base)
        if not job:
            raise HTTPException(404, "search not found")
        return job

    @api.get("/jobs/{job_id}")
    def get_job(job_id: str):
        job = store.get_job(job_id)
        if not job:
            raise HTTPException(404, "search not found")
        return job

    @api.post("/audit")
    def audit_one(req: AuditRequest):
        r = audit(req.url.strip())
        return {**r.to_dict(), "findings": [asdict(f) for f in r.findings]}

    @api.get("/leads")
    def list_leads(kind: str | None = None, status: str | None = None, q: str | None = None):
        has = {"site": True, "nosite": False}.get(kind or "")
        return store.list_leads(has, status or None, q or None)

    @api.get("/leads.csv")
    def export_csv(kind: str | None = None):
        has = {"site": True, "nosite": False}.get(kind or "")
        rows = store.list_leads(has)
        cols = ["status", "tier", "qual_score", "name", "email", "phone", "website", "category",
                "city", "site_score", "top_issue", "subject", "body", "message", "notes",
                "maps_url", "facebook_search"]
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        return Response("﻿" + buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": "attachment; filename=hala-leads.csv"})

    @api.get("/leads/{lead_id}")
    def get_lead(lead_id: int):
        lead = store.get_lead(lead_id)
        if not lead:
            raise HTTPException(404, "lead not found")
        return lead

    @api.patch("/leads/{lead_id}")
    def patch_lead(lead_id: int, patch: LeadPatch):
        try:
            lead = store.update_lead(lead_id, patch.model_dump(exclude_none=True))
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not lead:
            raise HTTPException(404, "lead not found")
        return lead

    @api.delete("/leads/{lead_id}")
    def delete_lead(lead_id: int):
        store.delete_lead(lead_id)
        return {"ok": True}

    @api.post("/leads/{lead_id}/refresh")
    def refresh_lead(lead_id: int):
        """Re-audit the site and rewrite the pitch (resets an edited pitch)."""
        lead = store.get_lead(lead_id)
        if not lead:
            raise HTTPException(404, "lead not found")
        if not lead["has_website"]:
            raise HTTPException(400, "this business has no website to audit")
        if lead["status"] != "new":
            store.update_lead(lead_id, {"status": "new"})
        settings = store.get_settings()
        process_site_lead(store, lead, settings, _claude_client(settings), local_base)
        store.update_lead(lead_id, {"status": lead["status"]})
        return store.get_lead(lead_id)

    @api.get("/stats")
    def stats():
        return {**store.stats(), "statuses": list(STATUSES)}

    @api.get("/reports.zip")
    def reports_zip():
        """All reports, named to match the links in the emails (for external hosting)."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for lead in store.list_leads(True):
                full = store.get_lead(lead["id"], with_report=True)
                if full and full["report_html"]:
                    z.writestr(f"{report_slug(full['report_token'], full['name'])}.html",
                               full["report_html"])
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": "attachment; filename=hala-reports.zip"})

    app.include_router(api)

    @app.get("/reports/{token}", response_class=HTMLResponse)
    def report(token: str):
        """Public on purpose: this is the page linked from outreach emails."""
        lead = store.get_lead_by_token(token)
        if not lead or not lead.get("report_html"):
            raise HTTPException(404, "report not found")
        return lead["report_html"]

    if not serve_static:
        return app
    if (STATIC_DIR / "index.html").exists():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    else:
        @app.get("/", response_class=HTMLResponse)
        def no_ui():
            return ("<h1>Hala API is running</h1><p>The web UI isn't built. Run "
                    "<code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code>.</p>")

    return app


def serve(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = True) -> None:
    import webbrowser

    import uvicorn

    url = f"http://localhost:{port}"
    app = create_app(local_base=url)
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"Hala is running at {url}  (press Ctrl+C to stop)")
    uvicorn.run(app, host=host, port=port, log_level="warning")
