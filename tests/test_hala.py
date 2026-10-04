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
