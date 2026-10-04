import io
import json
import urllib.error

from hala import ai
from hala.pitch import write_pitch
from tests.test_hala import bad

PITCH = {"subject": "calls from mobile", "body": "Hi...", "angle": "tap to call"}


def fake_open(responses, seen):
    """urlopen stand-in: each item is a dict (JSON reply) or (status, body) for an error."""
    def _open(req, timeout=0):
        seen.append({"url": req.full_url, "body": json.loads(req.data) if req.data else None,
                     "auth": req.get_header("Authorization")})
        item = responses.pop(0)
        if isinstance(item, tuple):
            raise urllib.error.HTTPError(req.full_url, item[0], "err", {}, io.BytesIO(item[1].encode()))
        return io.BytesIO(json.dumps(item).encode())
    return _open


def chat(content):
    return {"choices": [{"message": {"content": content}}]}


def test_openai_compatible_writer_parses_json_even_in_fences():
    seen = []
    w = ai.OpenAICompatWriter("https://api.groq.com/openai/v1", "gsk-1", "llama", name="groq",
                              _open=fake_open([chat("```json\n" + json.dumps(PITCH) + "\n```")], seen))
    pitch = write_pitch({"name": "X"}, bad(), "https://r", {"name": "A"}, writer=w)
    assert pitch.subject == "calls from mobile" and pitch.source == "groq"
    assert seen[0]["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert seen[0]["auth"] == "Bearer gsk-1" and seen[0]["body"]["model"] == "llama"
    assert seen[0]["body"]["response_format"] == {"type": "json_object"}


def test_retries_without_json_mode_when_unsupported():
    seen = []
    w = ai.OpenAICompatWriter("http://localhost:11434/v1", "", "llama3", name="custom",
                              _open=fake_open([(400, '{"error": {"message": "response_format not supported"}}'),
                                               chat(json.dumps(PITCH))], seen))
    assert w.generate("s", "u", {"required": ["subject"]}) == PITCH
    assert "response_format" not in seen[1]["body"] and seen[0]["auth"] is None


def test_errors_fall_back_to_template_with_reason():
    seen = []
    w = ai.OpenAICompatWriter("https://x/v1", "k", "nope", name="gemini",
                              _open=fake_open([(404, '[{"error": {"message": "models/nope is not found"}}]')], seen))
    pitch = write_pitch({"name": "X"}, bad(), "https://r", {"name": "A"}, writer=w)
    assert pitch.source == "template"
    assert w.last_error == "gemini error 404: models/nope is not found"


def test_missing_fields_rejected():
    w = ai.OpenAICompatWriter("https://x/v1", "k", "m", _open=fake_open([chat('{"subject": "x"}')], []))
    assert w.generate("s", "u", {"required": ["subject", "body"]}) is None
    assert "missing" in w.last_error


def test_writer_from_settings():
    base = {"use_ai": "1", "ai_model": ""}
    listed = lambda *a: ["gemini-2.5-flash", "gemini-3.0-flash", "text-embedding-004"]  # noqa: E731
    assert ai.writer_from_settings({**base, "ai_provider": "gemini"}, _list=listed) is None  # no key yet
    g = ai.writer_from_settings({**base, "ai_provider": "gemini", "gemini_api_key": "AIza"}, _list=listed)
    assert g.name == "gemini" and g.model == "gemini-3.0-flash"  # automatic: newest flash
    assert "generativelanguage.googleapis.com" in g.base_url
    o = ai.writer_from_settings({**base, "ai_provider": "openrouter", "openrouter_api_key": "k",
                                 "ai_model": "some/model:free"})
    assert o.model == "some/model:free"
    c = ai.writer_from_settings({**base, "ai_provider": "custom", "ai_base_url": "http://localhost:11434/v1",
                                 "ai_model": "llama3"}, _list=listed)
    assert c is not None and c.base_url == "http://localhost:11434/v1"  # local models need no key
    a = ai.writer_from_settings({**base, "ai_provider": "anthropic", "anthropic_api_key": "sk-ant"})
    assert isinstance(a, ai.AnthropicWriter)
    assert ai.writer_from_settings({**base, "use_ai": "0", "ai_provider": "gemini", "gemini_api_key": "k"}) is None


def test_automatic_model_survives_renames():
    groq = ["whisper-large-v3", "llama-3.1-8b-instant", "openai/gpt-oss-120b", "meta-llama/llama-guard-4-12b"]
    assert ai.choose_model("groq", groq) == "openai/gpt-oss-120b"
    assert ai.choose_model("openrouter", ["openai/gpt-4o", "qwen/qwen3-235b:free"]) == "qwen/qwen3-235b:free"
    assert ai.choose_model("custom", ["llama3.2"]) == "llama3.2"
    assert ai.choose_model("groq", ["whisper-large-v3"]) is None


def test_list_models_parses_and_caches():
    seen = []
    ai._model_cache.clear()
    reply = {"data": [{"id": "models/gemini-3.0-flash"}, {"id": "llama-3.3-70b-versatile"}]}
    ids = ai.list_models("gemini", "https://x/v1", "k", _open=fake_open([reply], seen))
    assert ids == ["gemini-3.0-flash", "llama-3.3-70b-versatile"] and seen[0]["url"] == "https://x/v1/models"
    assert ai.list_models("gemini", "https://x/v1", "k", _open=fake_open([], seen)) == ids  # cached


def test_model_listing_failure_falls_back_to_default():
    def boom(*a):
        raise RuntimeError("groq error 401: Invalid API Key")
    model, note = ai.resolve_model({"use_ai": "1", "ai_provider": "groq", "groq_api_key": "gsk_x"}, _list=boom)
    assert model == ai.PROVIDERS["groq"]["model"] and "Invalid API Key" in note
