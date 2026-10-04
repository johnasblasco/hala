from types import SimpleNamespace as NS

from hala.preview import build_preview, default_content, render_preview, safe_url

LEAD = {"name": "Santos Dental Clinic", "category": "dentist", "city": "Malolos City",
        "address": "12 Paseo del Congreso", "phone": "0917 123 4567", "rating": "4.8", "reviews": "52"}
SENDER = {"name": "Johnas", "company": "Hala Studio"}


def test_template_preview_has_essentials():
    html, source = build_preview(LEAD, SENDER)
    assert source == "template"
    assert "Santos Dental Clinic" in html and "Braces &amp; aligners" in html
    assert 'href="tel:09171234567"' in html and "Get directions" in html
    assert "Design preview" in html and "noindex" in html  # honest + not indexed
    assert "4.8 on Google · 52 reviews" in html
    assert "#0e9f9a" in html  # dentist colour theme


def test_owner_notes_become_services():
    c = default_content(LEAD, "Braces\nWhitening\nRoot canal")
    assert [s["name"] for s in c["services"]] == ["Braces", "Whitening", "Root canal"]


def test_everything_is_escaped_and_bad_links_dropped():
    evil = {**LEAD, "name": "<script>alert(1)</script>"}
    content = default_content(evil)
    content["headline"] = '<img src=x onerror="alert(1)">'
    html = render_preview(evil, content, SENDER,
                          photos=["javascript:alert(1)", "https://ok.example/a.jpg", "https://x/\"><b>"],
                          facebook_url="data:text/html,hi")
    assert "<script>alert(1)" not in html and "<img src=x" not in html
    assert "javascript:" not in html and "data:text/html" not in html
    assert "https://ok.example/a.jpg" in html
    assert safe_url("https://www.facebook.com/santosdental") == "https://www.facebook.com/santosdental"


def test_claude_writes_the_words_only():
    sent = {}

    class FakeMessages:
        def create(self, **kw):
            sent.update(kw)
            return NS(stop_reason="end_turn", content=[NS(type="text", text=(
                '{"headline": "Ngiting panalo sa Malolos", "subheadline": "Sub", '
                '"services": [{"name": "Braces", "description": "D"}], "why_us": ["A"], '
                '"about": "About", "faq": [{"q": "Q?", "a": "A."}], "cta": "Mag-book"}'))])
    html, source = build_preview(LEAD, SENDER, language="Taglish",
                                 client=NS(beta=NS(messages=FakeMessages())))
    assert source == "claude" and "Ngiting panalo sa Malolos" in html
    assert sent["model"] == "claude-opus-5-5"
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert '"language": "Taglish"' in sent["messages"][0]["content"]


def test_claude_refusal_falls_back_to_template():
    class FakeMessages:
        def create(self, **kw):
            return NS(stop_reason="refusal", content=[])
    _, source = build_preview(LEAD, SENDER, client=NS(beta=NS(messages=FakeMessages())))
    assert source == "template"
