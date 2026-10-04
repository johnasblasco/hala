import os
import uuid

import pytest
from fastapi.testclient import TestClient

from hala import find as finder
from hala import server
from hala.db import Store
from tests.test_hala import bad, good

PG_URL = os.environ.get("HALA_TEST_PG")  # e.g. postgresql://postgres@localhost:5432/postgres


def _stores():
    yield pytest.param("sqlite", id="sqlite")
    yield pytest.param("pg", id="postgres",
                       marks=pytest.mark.skipif(not PG_URL, reason="set HALA_TEST_PG to test Postgres"))


@pytest.fixture(params=list(_stores()))
def store(request):
    if request.param == "sqlite":
        return Store(":memory:")
    s = Store(PG_URL)
    with s._tx() as run:  # isolate each test
        for t in (s.leads, s.settings_t, s.jobs):
            run(f"TRUNCATE {t}")
    return s


@pytest.fixture
def client(store, monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "GOOGLE_MAPS_API_KEY", "HALA_SENDER_NAME", "SUPABASE_URL",
              "SUPABASE_ANON_KEY", "VERCEL", "HALA_ALLOWED_EMAILS"):
        monkeypatch.delenv(k, raising=False)
    return TestClient(server.create_app(store))


def run_job(client, queries=("dentist in Malolos",)):
    job = client.post("/api/search", json={"queries": list(queries)}).json()
    assert job["status"] == "queued"
    for _ in range(50):
        job = client.post(f"/api/jobs/{job['id']}/step").json()
        if job["status"] in ("done", "error"):
            return job
    raise AssertionError("job did not finish")


def fake_search(monkeypatch, n_extra_sites=0):
    leads = [
        {"name": "Bad Dental", "email": "hi@bad.ph", "website": "http://bad.ph", "category": "dentist",
         "city": "Malolos", "reviews": "120", "rating": "4.6", "runs_ads": "", "phone": "",
         "address": "1 St", "maps_url": ""},
        {"name": "Good Dental", "email": "", "website": "https://good.ph",
         "category": "dentist", "city": "Malolos", "reviews": "", "rating": "", "runs_ads": "",
         "phone": "", "address": "2 St", "maps_url": ""},
        {"name": "No Site Dental", "email": "", "website": "", "category": "dentist",
         "city": "Malolos", "reviews": "", "rating": "", "runs_ads": "", "phone": "0917",
         "address": "3 St", "maps_url": ""},
    ]
    for i in range(n_extra_sites):
        leads.append({**leads[0], "name": f"Extra {i}", "address": f"{i} Ave", "website": "http://bad.ph"})
    monkeypatch.setattr(finder, "osm_search", lambda **kw: (lambda q, m: [dict(l) for l in leads]))
    monkeypatch.setattr(finder, "find_email", lambda url: "found@site.ph")
    pages = {"http://bad.ph": bad(), "https://good.ph": good()}
    monkeypatch.setattr(server, "audit", lambda url: pages[url])


def test_search_job_stores_leads(client, monkeypatch):
    fake_search(monkeypatch)
    job = run_job(client)
    assert job["status"] == "done", job
    assert job["with_website"] == 2 and job["no_website"] == 1 and job["done"] == 2

    sites = client.get("/api/leads?kind=site").json()
    bad_lead = sites[0]
    assert bad_lead["name"] == "Bad Dental"
    assert bad_lead["subject"] and f"/reports/{bad_lead['report_token']}" in bad_lead["body"]
    assert any(f["id"] == "no_https" for f in bad_lead["findings"])
    good_lead = next(l for l in sites if l["name"] == "Good Dental")
    assert good_lead["tier"] == "skip" and good_lead["subject"] == ""
    assert good_lead["email"] == "found@site.ph"  # looked up during the audit step

    nosite = client.get("/api/leads?kind=nosite").json()
    assert nosite[0]["message"] and "facebook.com" in nosite[0]["facebook_search"]

    r = client.get(f"/reports/{bad_lead['report_token']}")
    assert r.status_code == 200 and "website check" in r.text
    assert client.get(f"/reports/{bad_lead['id']}").status_code == 404  # ids aren't guessable links


def test_job_runs_in_small_steps(client, monkeypatch):
    fake_search(monkeypatch, n_extra_sites=7)  # 9 websites -> search step + 3 audit steps
    job = client.post("/api/search", json={"queries": ["dentist in Malolos"]}).json()
    seen = []
    while job["status"] not in ("done", "error"):
        job = client.post(f"/api/jobs/{job['id']}/step").json()
        seen.append((job["status"], job["done"]))
    assert seen == [("running", 0), ("running", 4), ("running", 8), ("done", 9)]


def test_step_is_skipped_while_another_holds_the_lease(client, store, monkeypatch):
    fake_search(monkeypatch)
    job = client.post("/api/search", json={"queries": ["dentist in Malolos"]}).json()
    assert store.claim_job(job["id"], 60)
    assert client.post(f"/api/jobs/{job['id']}/step").json()["status"] == "queued"
    store.release_job(job["id"])
    assert client.post(f"/api/jobs/{job['id']}/step").json()["status"] == "running"


def test_status_updates_and_repeat_search_keeps_user_work(client, monkeypatch):
    fake_search(monkeypatch)
    run_job(client)
    lead = client.get("/api/leads?kind=site").json()[0]
    r = client.patch(f"/api/leads/{lead['id']}",
                     json={"status": "contacted", "body": "my edited email", "notes": "called"})
    assert r.json()["status"] == "contacted"
    assert client.patch(f"/api/leads/{lead['id']}", json={"status": "bogus"}).status_code == 400

    run_job(client)
    again = client.get(f"/api/leads/{lead['id']}").json()
    assert again["status"] == "contacted" and again["body"] == "my edited email"
    assert len(client.get("/api/leads").json()) == 3  # no duplicates

    stats = client.get("/api/stats").json()
    assert stats["by_status"]["contacted"] == 1 and stats["total"] == 3
    assert client.get("/api/leads?q=BAD").json()[0]["name"] == "Bad Dental"  # case-insensitive


def test_settings_hide_secrets(client):
    r = client.put("/api/settings", json={"sender_name": "Johnas", "anthropic_api_key": "sk-secret"})
    body = r.json()
    assert body["sender_name"] == "Johnas"
    assert body["anthropic_api_key_set"] is True and "sk-secret" not in r.text
    assert client.put("/api/settings", json={"anthropic_api_key": ""}).json()["anthropic_api_key_set"]
    assert not client.delete("/api/settings/anthropic_api_key").json()["anthropic_api_key_set"]


def test_search_error_is_reported(client, monkeypatch):
    def boom(**kw):
        def search(q, m):
            raise RuntimeError("OpenStreetMap's free servers are busy right now")
        return search
    monkeypatch.setattr(finder, "osm_search", boom)
    job = run_job(client, ["dentist in X"])
    assert job["status"] == "error" and "OpenStreetMap" in job["error"]


def test_csv_and_zip_export(client, monkeypatch):
    fake_search(monkeypatch)
    run_job(client)
    assert "Bad Dental" in client.get("/api/leads.csv").text
    z = client.get("/api/reports.zip")
    assert z.status_code == 200 and z.content[:2] == b"PK"


def test_quick_audit(client, monkeypatch):
    monkeypatch.setattr(server, "audit", lambda url: bad())
    r = client.post("/api/audit", json={"url": "http://bad.ph"}).json()
    assert r["score"] < 50 and r["findings"][0]["impact"] == 3


# --- auth ------------------------------------------------------------------

@pytest.fixture
def auth_client(store, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("HALA_ALLOWED_EMAILS", "johnas@example.com, Partner@Example.com")
    users = {"good-token": "johnas@example.com", "partner-token": "partner@example.com",
             "stranger-token": "someone@else.com"}
    monkeypatch.setattr(server, "verify_token", lambda token, cfg: users.get(token))
    return TestClient(server.create_app(store))


def test_login_required_when_supabase_configured(auth_client, monkeypatch):
    cfg = auth_client.get("/api/config").json()
    assert cfg["auth"] == {"supabase_url": "https://proj.supabase.co", "anon_key": "anon-key"}
    assert auth_client.get("/api/stats").status_code == 401
    bad_tok = auth_client.get("/api/stats", headers={"Authorization": "Bearer expired"})
    assert bad_tok.status_code == 401
    stranger = auth_client.get("/api/stats", headers={"Authorization": "Bearer stranger-token"})
    assert stranger.status_code == 403 and "someone@else.com" in stranger.json()["detail"]
    ok = auth_client.get("/api/me", headers={"Authorization": "Bearer partner-token"})
    assert ok.status_code == 200 and ok.json()["email"] == "partner@example.com"


def test_reports_stay_public_with_login_on(auth_client, store):
    lead_id = store.upsert_lead({"name": "X", "address": "1", "website": "http://x", "has_website": 1,
                                 "report_html": "<p>report</p>"})
    token = store.get_lead(lead_id)["report_token"]
    assert auth_client.get(f"/reports/{token}").text == "<p>report</p>"


def test_vercel_without_login_config_refuses(store, monkeypatch):
    for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "HALA_ALLOW_NO_AUTH"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VERCEL", "1")
    c = TestClient(server.create_app(store))
    r = c.get("/api/stats")
    assert r.status_code == 503 and "SUPABASE_URL" in r.json()["detail"]


def test_verify_token_caches(monkeypatch):
    import io
    calls = []

    def fake_open(req, timeout=0):
        calls.append(req.full_url)
        assert req.get_header("Apikey") == "anon"
        return io.BytesIO(b'{"email": "Johnas@Example.com"}')
    monkeypatch.setattr(server.urllib.request, "urlopen", fake_open)
    cfg = {"url": "https://p.supabase.co", "anon_key": "anon"}
    tok = uuid.uuid4().hex
    assert server.verify_token(tok, cfg) == "johnas@example.com"
    assert server.verify_token(tok, cfg) == "johnas@example.com"
    assert calls == ["https://p.supabase.co/auth/v1/user"]


def test_config_and_health_work_when_database_is_down(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://p.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("HALA_ALLOWED_EMAILS", "a@b.c")
    monkeypatch.setattr(server, "verify_token", lambda t, c: "a@b.c")
    c = TestClient(server.create_app())  # must not crash at startup
    assert c.get("/api/config").status_code == 200
    h = c.get("/api/health").json()
    assert "DATABASE_URL isn't set" in h["database"] and h["login"] == "on"
    r = c.get("/api/stats", headers={"Authorization": "Bearer x"})
    assert r.status_code == 503 and "DATABASE_URL" in r.json()["detail"]


def test_bad_postgres_url_gives_readable_error():
    from hala.db import DatabaseUnavailable
    s = Store("postgresql://postgres.abc:[YOUR-PASSWORD]@127.0.0.1:1/postgres")  # nothing listens
    with pytest.raises(DatabaseUnavailable) as e:
        s.check()
    assert "still contains [YOUR-PASSWORD]" in str(e.value)
    with pytest.raises(DatabaseUnavailable) as e:
        Store("postgresql://postgres.abc:s3cretpw@127.0.0.1:1/postgres").check()
    assert "Connection refused" in str(e.value) and "s3cretpw" not in str(e.value)


def test_supabase_url_suffixes_are_stripped(monkeypatch):
    for raw in ("https://p.supabase.co/rest/v1/", "https://p.supabase.co/auth/v1", " https://p.supabase.co/ "):
        monkeypatch.setenv("SUPABASE_URL", raw)
        monkeypatch.setenv("SUPABASE_ANON_KEY", "k")
        assert server.auth_config()["url"] == "https://p.supabase.co"


def test_preview_endpoint_and_public_page(client, store):
    lead_id = store.upsert_lead({"name": "Santos Dental", "address": "1 St", "category": "dentist",
                                 "city": "Malolos City", "phone": "0917", "has_website": 0})
    r = client.post(f"/api/leads/{lead_id}/preview",
                    json={"notes": "Braces, Whitening", "facebook_url": "https://facebook.com/santos"})
    body = r.json()
    assert r.status_code == 200 and body["preview_source"] == "template"
    assert body["preview_url"].endswith(f"/preview/{body['preview_token']}")
    page = client.get(f"/preview/{body['preview_token']}")
    assert page.status_code == 200 and "Santos Dental" in page.text and "Whitening" in page.text
    # regenerating keeps the same link
    again = client.post(f"/api/leads/{lead_id}/preview", json={"notes": "Dentures"}).json()
    assert again["preview_token"] == body["preview_token"]
    assert "Dentures" in client.get(f"/preview/{body['preview_token']}").text
    assert "preview_html" not in client.get("/api/leads").json()[0]  # list stays light
    assert client.get("/preview/nope").status_code == 404
    assert client.post(f"/api/leads/{lead_id}/preview", json={"language": "Klingon"}).status_code == 400
