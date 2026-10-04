import time

import pytest
from fastapi.testclient import TestClient

from hala import find as finder
from hala import server
from hala.db import Store
from tests.test_hala import bad, good


@pytest.fixture
def client(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "GOOGLE_MAPS_API_KEY", "HALA_SENDER_NAME"):
        monkeypatch.delenv(k, raising=False)
    store = Store(":memory:")
    return TestClient(server.create_app(store))


def wait(client, job_id):
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def fake_search(monkeypatch):
    leads = [
        {"name": "Bad Dental", "email": "hi@bad.ph", "website": "http://bad.ph", "category": "dentist",
         "city": "Malolos", "reviews": "120", "rating": "4.6", "runs_ads": "", "phone": "",
         "address": "1 St", "maps_url": ""},
        {"name": "Good Dental", "email": "hi@good.ph", "website": "https://good.ph",
         "category": "dentist", "city": "Malolos", "reviews": "", "rating": "", "runs_ads": "",
         "phone": "", "address": "2 St", "maps_url": ""},
        {"name": "No Site Dental", "email": "", "website": "", "category": "dentist",
         "city": "Malolos", "reviews": "", "rating": "", "runs_ads": "", "phone": "0917",
         "address": "3 St", "maps_url": ""},
    ]
    monkeypatch.setattr(finder, "osm_search", lambda: (lambda q, m: [dict(l) for l in leads]))
    monkeypatch.setattr(finder, "find_email", lambda url: "")
    pages = {"http://bad.ph": bad(), "https://good.ph": good()}
    monkeypatch.setattr(server, "audit", lambda url: pages[url])


def test_search_job_stores_leads(client, monkeypatch):
    fake_search(monkeypatch)
    job = client.post("/api/search", json={"queries": ["dentist in Malolos"]}).json()
    job = wait(client, job["id"])
    assert job["status"] == "done", job
    assert job["with_website"] == 2 and job["no_website"] == 1

    sites = client.get("/api/leads?kind=site").json()
    assert [l["name"] for l in sites][0] == "Bad Dental"
    bad_lead = sites[0]
    assert bad_lead["subject"] and "reports/" in bad_lead["body"]
    assert any(f["id"] == "no_https" for f in bad_lead["findings"])
    good_lead = next(l for l in sites if l["name"] == "Good Dental")
    assert good_lead["tier"] == "skip" and good_lead["subject"] == ""

    nosite = client.get("/api/leads?kind=nosite").json()
    assert nosite[0]["message"] and "facebook.com" in nosite[0]["facebook_search"]

    r = client.get(f"/reports/{bad_lead['id']}")
    assert r.status_code == 200 and "website check" in r.text


def test_status_updates_and_repeat_search_keeps_user_work(client, monkeypatch):
    fake_search(monkeypatch)
    wait(client, client.post("/api/search", json={"queries": ["dentist in Malolos"]}).json()["id"])
    lead = client.get("/api/leads?kind=site").json()[0]
    r = client.patch(f"/api/leads/{lead['id']}",
                     json={"status": "contacted", "body": "my edited email", "notes": "called"})
    assert r.json()["status"] == "contacted"
    assert client.patch(f"/api/leads/{lead['id']}", json={"status": "bogus"}).status_code == 400

    wait(client, client.post("/api/search", json={"queries": ["dentist in Malolos"]}).json()["id"])
    again = client.get(f"/api/leads/{lead['id']}").json()
    assert again["status"] == "contacted" and again["body"] == "my edited email"
    assert len(client.get("/api/leads").json()) == 3  # no duplicates

    stats = client.get("/api/stats").json()
    assert stats["by_status"]["contacted"] == 1 and stats["total"] == 3


def test_settings_hide_secrets(client):
    r = client.put("/api/settings", json={"sender_name": "Johnas", "anthropic_api_key": "sk-secret"})
    body = r.json()
    assert body["sender_name"] == "Johnas"
    assert body["anthropic_api_key_set"] is True and "sk-secret" not in r.text
    # blank secret keeps the stored one
    assert client.put("/api/settings", json={"anthropic_api_key": ""}).json()["anthropic_api_key_set"]
    assert not client.delete("/api/settings/anthropic_api_key").json()["anthropic_api_key_set"]


def test_search_error_is_reported(client, monkeypatch):
    def boom():
        def search(q, m):
            raise RuntimeError("all OpenStreetMap servers failed")
        return search
    monkeypatch.setattr(finder, "osm_search", boom)
    job = wait(client, client.post("/api/search", json={"queries": ["dentist in X"]}).json()["id"])
    assert job["status"] == "error" and "OpenStreetMap" in job["error"]


def test_csv_and_zip_export(client, monkeypatch):
    fake_search(monkeypatch)
    wait(client, client.post("/api/search", json={"queries": ["dentist in Malolos"]}).json()["id"])
    csv_text = client.get("/api/leads.csv").text
    assert "Bad Dental" in csv_text
    z = client.get("/api/reports.zip")
    assert z.status_code == 200 and z.content[:2] == b"PK"


def test_quick_audit(client, monkeypatch):
    monkeypatch.setattr(server, "audit", lambda url: bad())
    r = client.post("/api/audit", json={"url": "http://bad.ph"}).json()
    assert r["score"] < 50 and r["findings"][0]["impact"] == 3
