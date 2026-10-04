"""Web API and static file server for the Hala GUI.

    hala serve            # http://localhost:8000
"""

from __future__ import annotations

import csv
import io
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import find as finder
from .audit import AuditResult, Finding, audit
from .db import STATUSES, SECRET_KEYS, Store
from .pitch import no_website_message, write_pitch
from .qualify import qualify
from .report import render_report, slugify

STATIC_DIR = Path(__file__).parent / "static"


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


def _audit_from_lead(lead: dict) -> AuditResult:
    """Rebuild an AuditResult from stored data (for re-pitching without re-fetching)."""
    r = AuditResult(url=lead["website"], reachable=lead.get("reachable") is not False)
    r.findings = [Finding(**f) for f in lead.get("findings", [])]
    return r


def report_slug(lead_id: int, name: str) -> str:
    return f"{slugify(name)}-{lead_id}"


def report_url(settings: dict, lead_id: int, name: str, local_base: str) -> str:
    base = (settings.get("report_base_url") or "").rstrip("/")
    if base:
        return f"{base}/{report_slug(lead_id, name)}.html"
    return f"{local_base}/reports/{lead_id}"


def process_site_lead(store: Store, lead: dict, settings: dict, client, local_base: str,
                      result: AuditResult | None = None) -> int:
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
    sender = store.sender()
    report = render_report(lead, result, sender)
    pitch_data: dict = {}
    if q.tier != "skip":
        url = report_url(settings, lead_id, lead.get("name", ""), local_base)
        p = write_pitch(lead, result, url, sender, use_claude=client is not None, client=client)
        pitch_data = {"subject": p.subject, "body": p.body, "angle": p.angle,
                      "pitch_source": p.source}
    store.upsert_lead({**data, "report_html": report, **pitch_data})
    return lead_id


class Jobs:
    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self) -> dict:
        job = {"id": uuid.uuid4().hex[:12], "status": "running", "stage": "Starting",
               "done": 0, "total": 0, "error": None, "with_website": 0, "no_website": 0}
        with self._lock:
            self._jobs[job["id"]] = job
        return job

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def update(self, job: dict, **kw) -> None:
        with self._lock:
            job.update(kw)


def run_search(store: Store, jobs: Jobs, job: dict, req: SearchRequest, local_base: str) -> None:
    try:
        settings = store.get_settings()
        source = req.source
        if source == "auto":
            source = "google" if settings["google_api_key"] else "osm"
        if source == "google":
            if not settings["google_api_key"]:
                raise RuntimeError("Add a Google API key in Settings, or use OpenStreetMap.")
            search = finder.google_search(settings["google_api_key"])
        else:
            search = finder.osm_search(notify=lambda m: jobs.update(job, stage=m))
        queries = list(dict.fromkeys(q.strip() for q in req.queries if q.strip()))
        if not queries:
            raise RuntimeError("Enter at least one search.")

        jobs.update(job, stage=f"Searching {'Google Maps' if source == 'google' else 'OpenStreetMap'}")
        with_site, no_site = finder.find_leads(queries, search, req.max_per_query)
        query_label = ", ".join(queries)

        sender = store.sender()
        for lead in no_site:
            store.upsert_lead({**lead, "has_website": 0, "search_query": query_label,
                               "facebook_search": finder.facebook_search_url(lead),
                               "message": no_website_message(lead, sender)})
        jobs.update(job, no_website=len(no_site), with_website=len(with_site),
                    total=len(with_site), stage="Auditing websites")

        client = _claude_client(settings)
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(audit, l["website"]): l for l in with_site}
            for fut in as_completed(futures):
                lead = {**futures[fut], "search_query": query_label}
                process_site_lead(store, lead, settings, client, local_base, fut.result())
                jobs.update(job, done=job["done"] + 1)
        jobs.update(job, status="done", stage="Done")
    except Exception as e:  # surfaced to the UI
        jobs.update(job, status="error", error=str(e), stage="Failed")


# --- app -------------------------------------------------------------------

def create_app(store: Store | None = None, local_base: str = "http://localhost:8000") -> FastAPI:
    store = store or Store()
    jobs = Jobs()
    app = FastAPI(title="Hala")
    app.state.store = store

    @app.get("/api/settings")
    def get_settings():
        s = store.get_settings()
        # Never send secrets back to the browser; only whether they are set.
        for k in SECRET_KEYS:
            s[k + "_set"] = bool(s.pop(k))
        return s

    @app.put("/api/settings")
    def put_settings(patch: SettingsPatch):
        values = patch.model_dump(exclude_none=True)
        for k in SECRET_KEYS:
            if values.get(k) == "":
                values.pop(k)  # blank secret field = keep the existing value
        store.save_settings(values)
        return get_settings()

    @app.delete("/api/settings/{key}")
    def clear_secret(key: str):
        if key not in SECRET_KEYS:
            raise HTTPException(400, "only API keys can be cleared")
        store.save_settings({key: ""})
        return get_settings()

    @app.post("/api/search")
    def start_search(req: SearchRequest):
        job = jobs.create()
        threading.Thread(target=run_search, args=(store, jobs, job, req, local_base),
                         daemon=True).start()
        return jobs.get(job["id"])

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        return job

    @app.post("/api/audit")
    def audit_one(req: AuditRequest):
        r = audit(req.url.strip())
        return {**r.to_dict(), "findings": [asdict(f) for f in r.findings]}

    @app.get("/api/leads")
    def list_leads(kind: str | None = None, status: str | None = None, q: str | None = None):
        has = {"site": True, "nosite": False}.get(kind or "")
        return store.list_leads(has, status or None, q or None)

    @app.get("/api/leads.csv")
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

    @app.get("/api/leads/{lead_id}")
    def get_lead(lead_id: int):
        lead = store.get_lead(lead_id)
        if not lead:
            raise HTTPException(404, "lead not found")
        return lead

    @app.patch("/api/leads/{lead_id}")
    def patch_lead(lead_id: int, patch: LeadPatch):
        try:
            lead = store.update_lead(lead_id, patch.model_dump(exclude_none=True))
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not lead:
            raise HTTPException(404, "lead not found")
        return lead

    @app.delete("/api/leads/{lead_id}")
    def delete_lead(lead_id: int):
        store.delete_lead(lead_id)
        return {"ok": True}

    @app.post("/api/leads/{lead_id}/refresh")
    def refresh_lead(lead_id: int):
        """Re-audit the site and rewrite the pitch (resets an edited pitch)."""
        lead = store.get_lead(lead_id)
        if not lead:
            raise HTTPException(404, "lead not found")
        if not lead["has_website"]:
            raise HTTPException(400, "this business has no website to audit")
        if lead["status"] != "new":
            store.update_lead(lead_id, {"status": "new"})
        process_site_lead(store, lead, store.get_settings(), _claude_client(store.get_settings()),
                          local_base)
        store.update_lead(lead_id, {"status": lead["status"]})
        return store.get_lead(lead_id)

    @app.get("/api/stats")
    def stats():
        return {**store.stats(), "statuses": list(STATUSES)}

    @app.get("/reports/{lead_id}", response_class=HTMLResponse)
    def report(lead_id: int):
        lead = store.get_lead(lead_id, with_report=True)
        if not lead or not lead.get("report_html"):
            raise HTTPException(404, "no report for this lead")
        return lead["report_html"]

    @app.get("/api/reports.zip")
    def reports_zip():
        """All reports, named to match the links in the emails, for Cloudflare Pages."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for lead in store.list_leads(True):
                full = store.get_lead(lead["id"], with_report=True)
                if full and full["report_html"]:
                    z.writestr(f"{report_slug(lead['id'], lead['name'])}.html", full["report_html"])
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": "attachment; filename=hala-reports.zip"})

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
