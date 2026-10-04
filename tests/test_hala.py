import csv
import datetime as dt
from pathlib import Path

from hala import audit as audit_mod
from hala.audit import AuditResult, analyze_html
from hala.cli import main
from hala.pitch import write_pitch
from hala.qualify import qualify
from hala.report import render_report

FIX = Path(__file__).parent / "fixtures"
TODAY = dt.date(2026, 10, 3)
SENDER = {"name": "Ana", "company": "Hala Studio", "address": "1 Ayala Ave, Makati",
          "email": "ana@hala.example"}


def bad():
    return analyze_html((FIX / "bad.html").read_text(), "http://mangjose.example",
                        load_seconds=3.4, today=TODAY)


def good():
    return analyze_html((FIX / "good.html").read_text(), "https://mangjose.example",
                        load_seconds=0.4, today=TODAY)


def test_bad_site_findings_ranked_by_impact():
    r = bad()
    ids = [f.id for f in r.findings]
    for expected in ("no_https", "not_mobile", "no_click_to_call", "slow",
                     "weak_title", "stale", "img_alt", "no_schema"):
        assert expected in ids
    impacts = [f.impact for f in r.findings]
    assert impacts == sorted(impacts, reverse=True)
    assert r.score < 30


def test_good_site_is_clean():
    r = good()
    assert r.findings == []
    assert r.score == 100


def test_unreachable_site_scores_zero(monkeypatch):
    def boom(url, timeout=0):
        raise OSError("connection refused")
    monkeypatch.setattr(audit_mod, "fetch", boom)
    r = audit_mod.audit("https://down.example")
    assert not r.reachable and r.score == 0
    assert r.top_finding.id == "unreachable"


def test_qualify_prefers_paying_businesses():
    lead_rich = {"email": "a@x", "category": "Dentist", "reviews": "250", "rating": "4.8",
                 "runs_ads": "yes"}
    lead_poor = {"email": "b@x", "category": "Cafe", "reviews": "3", "rating": "3.9"}
    a, b = qualify(lead_rich, bad()), qualify(lead_poor, bad())
    assert a.score > b.score and a.tier == "A"


def test_qualify_skips_no_email_and_good_sites():
    assert qualify({"email": ""}, bad()).tier == "skip"
    assert qualify({"email": "a@x", "runs_ads": "yes"}, good()).tier == "skip"


def test_report_escapes_and_includes_findings():
    html = render_report({"name": "<script>x</script>"}, bad(), SENDER)
    assert "<script>x</script>" not in html
    assert "Phone visitors can't tap to call you" in html or "tap to call" in html


def test_template_pitch_has_compliance_footer(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    p = write_pitch({"name": "Mang Jose Plumbing"}, bad(), "https://r/x.html", SENDER)
    assert p.source == "template"
    assert "https://r/x.html" in p.body
    assert "1 Ayala Ave, Makati" in p.body and "no thanks" in p.body


def test_run_pipeline(tmp_path, monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    pages = {"http://bad.example": bad(), "https://good.example": good()}
    monkeypatch.setattr("hala.cli.audit", lambda url: pages[url])
    leads = tmp_path / "leads.csv"
    leads.write_text("name,email,website,category,reviews,runs_ads\n"
                     "Bad Co,b@x,http://bad.example,Plumber,80,yes\n"
                     "Good Co,g@x,https://good.example,Plumber,80,yes\n"
                     "No Email,,http://bad.example,Plumber,80,yes\n")
    out = tmp_path / "out"
    assert main(["run", str(leads), "--out", str(out), "--no-ai",
                 "--report-base-url", "https://audits.example/"]) == 0
    rows = list(csv.DictReader(open(out / "campaign.csv")))
    assert [r["name"] for r in rows] == ["Bad Co"]
    assert rows[0]["report_url"] == "https://audits.example/bad-co.html"
    assert (out / "reports" / "bad-co.html").exists()


def test_claude_pitch_parses_structured_output():
    from types import SimpleNamespace as NS
    from hala.pitch import claude_pitch

    calls = {}

    class FakeMessages:
        def create(self, **kw):
            calls.update(kw)
            return NS(stop_reason="end_turn", content=[NS(
                type="text",
                text='{"subject": "calls from mobile", "body": "Hi...", "angle": "tap to call"}')])

    client = NS(beta=NS(messages=FakeMessages()))
    p = claude_pitch({"name": "X"}, bad(), "https://r", client=client)
    assert p.subject == "calls from mobile" and p.source == "claude"
    assert calls["model"] == "claude-opus-5-5"
    assert calls["output_config"]["format"]["type"] == "json_schema"


def test_claude_refusal_falls_back_to_none():
    from types import SimpleNamespace as NS
    from hala.pitch import claude_pitch

    class FakeMessages:
        def create(self, **kw):
            return NS(stop_reason="refusal", content=[])

    assert claude_pitch({}, bad(), "u", client=NS(beta=NS(messages=FakeMessages()))) is None


def test_extract_emails_prefers_own_domain_and_skips_junk():
    from hala.find import extract_emails
    html = ('<a href="mailto:jane@gmail.com">x</a> info@brightsmile.ph '
            'logo@2x.png user@example.com 123@sentry.wixpress.com')
    assert extract_emails(html, "www.brightsmile.ph") == ["info@brightsmile.ph", "jane@gmail.com"]


def test_find_email_tries_contact_pages():
    from hala.find import find_email
    pages = {"https://a.ph/contact": "<p>Email us: hello@a.ph</p>"}
    assert find_email("https://a.ph", _get_page=pages.get) == "hello@a.ph"
    assert find_email("https://none.ph", _get_page=lambda u: "<p>no email</p>") == ""


def test_search_places_paginates():
    from hala.find import search_places
    pages = [{"places": [{"displayName": {"text": f"A{i}"}} for i in range(20)], "nextPageToken": "t"},
             {"places": [{"displayName": {"text": "B"}}]}]
    sent = []

    def post(url, body, headers):
        sent.append(body)
        return pages[len(sent) - 1]
    out = search_places("dentist", "KEY", _post=post)
    assert len(out) == 21 and sent[1]["pageToken"] == "t"


def test_find_command_splits_no_website(tmp_path, monkeypatch):
    from hala import find as finder
    places = [
        {"displayName": {"text": "Bright Smile"}, "websiteUri": "https://bs.ph", "rating": 4.8,
         "userRatingCount": 200, "formattedAddress": "1 St, Brgy X, Quezon City, Metro Manila, Philippines",
         "primaryTypeDisplayName": {"text": "Dentist"}},
        {"displayName": {"text": "No Site Dental"}, "formattedAddress": "2 St, Makati, Metro Manila, Philippines",
         "nationalPhoneNumber": "0917 000 0000"},
    ]
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "KEY")
    monkeypatch.setattr(finder, "search_places", lambda q, k, m: places)
    monkeypatch.setattr(finder, "find_email", lambda url: "info@bs.ph")
    out = tmp_path / "leads.csv"
    assert main(["find", "dentist in QC", "--out", str(out)]) == 0
    rows = list(csv.DictReader(open(out, encoding="utf-8-sig")))
    assert rows[0]["email"] == "info@bs.ph" and rows[0]["city"] == "Quezon City"
    assert rows[0]["reviews"] == "200" and rows[0]["category"] == "Dentist"
    nosite = list(csv.DictReader(open(tmp_path / "leads-no-website.csv", encoding="utf-8-sig")))
    assert nosite[0]["name"] == "No Site Dental"


def test_split_query_and_tags():
    from hala.find import osm_tag_filters, split_query
    assert split_query("dentists in Quezon City") == ("dentists", "Quezon City")
    assert '["amenity"="dentist"]' in osm_tag_filters("dentists")
    assert osm_tag_filters("tattoo")[0].startswith('["name"~"tattoo",i]')


def test_osm_search_builds_leads(monkeypatch):
    from hala import find as finder
    monkeypatch.setattr(finder.time, "sleep", lambda s: None)
    sent = {}

    def fake_overpass(q):
        sent["q"] = q
        return {"elements": [
            {"type": "node", "id": 1, "lat": 14.6, "lon": 121.0,
             "tags": {"name": "Smile Dental", "amenity": "dentist", "website": "smile.ph",
                      "phone": "+63 2 8123 4567", "addr:street": "Katipunan Ave"}},
            {"type": "way", "id": 2, "center": {"lat": 14.6, "lon": 121.0},
             "tags": {"name": "Tooth Co", "amenity": "dentist", "contact:email": "hi@tooth.ph"}},
            {"type": "node", "id": 3, "tags": {"amenity": "dentist"}},  # no name: dropped
        ]}
    search = finder.osm_search(_overpass_fn=fake_overpass, _geocode=lambda p: (14.5, 120.9, 14.8, 121.2))
    leads = search("dentist in Quezon City", 60)
    assert '["amenity"="dentist"](14.5,120.9,14.8,121.2)' in sent["q"]
    assert [l["name"] for l in leads] == ["Smile Dental", "Tooth Co"]
    assert leads[0]["website"] == "http://smile.ph" and leads[0]["city"] == "Quezon City"
    assert leads[1]["email"] == "hi@tooth.ph"
    assert leads[0]["maps_url"] == "https://www.openstreetmap.org/node/1"


def test_find_defaults_to_free_osm(tmp_path, monkeypatch):
    from hala import find as finder
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    lead = {"name": "Smile", "email": "", "website": "http://smile.ph", "category": "dentist",
            "city": "QC", "reviews": "", "rating": "", "runs_ads": "", "phone": "",
            "address": "", "maps_url": ""}
    monkeypatch.setattr(finder, "osm_search", lambda: (lambda q, m: [dict(lead)]))
    monkeypatch.setattr(finder, "find_email", lambda url: "hi@smile.ph")
    out = tmp_path / "leads.csv"
    assert main(["find", "dentist in QC", "--out", str(out)]) == 0
    rows = list(csv.DictReader(open(out, encoding="utf-8-sig")))
    assert rows[0]["email"] == "hi@smile.ph"


def test_overpass_falls_back_to_next_server():
    import io
    import urllib.error
    from hala import find as finder
    tried = []

    def fake_open(req, timeout=0):
        tried.append(req.full_url)
        assert "Mozilla" not in req.get_header("User-agent")
        if len(tried) == 1:
            raise urllib.error.HTTPError(req.full_url, 406, "Not Acceptable", {}, io.BytesIO(b""))
        return io.BytesIO(b'{"elements": []}')
    assert finder._overpass("[out:json];", _open=fake_open) == {"elements": []}
    assert tried[0] == finder.OVERPASS_URLS[0] and tried[1] == finder.OVERPASS_URLS[1]


def test_overpass_all_fail_message():
    import io
    import urllib.error
    import pytest
    from hala import find as finder

    def fake_open(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 406, "x", {}, io.BytesIO(b""))
    with pytest.raises(RuntimeError, match="overpass-api.de: HTTP 406"):
        finder._overpass("q", _open=fake_open)
