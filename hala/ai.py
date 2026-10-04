"""AI writers: one interface over Anthropic (Claude) and any OpenAI-compatible API
(Gemini, Groq, OpenRouter, OpenAI, Ollama, ...).

A writer turns (system prompt, user content, JSON schema) into a dict, or None
when the provider fails or declines. Callers always have a template fallback,
so a missing key, an exhausted free tier or a bad model name never breaks the app.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

ANTHROPIC_MODEL = "claude-opus-5-5"

# Model defaults are suggestions: every provider renames models over time, so
# the model is editable in Settings and the Test button reports a bad name.
PROVIDERS = {
    "anthropic": {"label": "Anthropic (Claude)", "base_url": "", "model": ANTHROPIC_MODEL,
                  "key_url": "https://console.anthropic.com/settings/keys", "env": "ANTHROPIC_API_KEY"},
    "gemini": {"label": "Google Gemini", "model": "gemini-2.5-flash",
               "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "key_url": "https://aistudio.google.com/apikey", "env": "GEMINI_API_KEY"},
    "groq": {"label": "Groq", "model": "llama-3.3-70b-versatile",
             "base_url": "https://api.groq.com/openai/v1",
             "key_url": "https://console.groq.com/keys", "env": "GROQ_API_KEY"},
    "openrouter": {"label": "OpenRouter", "model": "meta-llama/llama-3.3-70b-instruct:free",
                   "base_url": "https://openrouter.ai/api/v1",
                   "key_url": "https://openrouter.ai/keys", "env": "OPENROUTER_API_KEY"},
    "openai": {"label": "OpenAI", "model": "gpt-5-mini", "base_url": "https://api.openai.com/v1",
               "key_url": "https://platform.openai.com/api-keys", "env": "OPENAI_API_KEY"},
    "custom": {"label": "Custom (OpenAI-compatible, e.g. Ollama)", "model": "", "base_url": "",
               "key_url": "", "env": ""},
}


def key_setting(provider: str) -> str:
    """Settings key holding this provider's API key."""
    return f"{provider}_api_key"


class Writer:
    name = "ai"
    last_error: str | None = None

    def generate(self, system: str, user: str, schema: dict, effort: str = "medium") -> dict | None:
        raise NotImplementedError


class AnthropicWriter(Writer):
    name = "claude"

    def __init__(self, client=None, api_key: str | None = None, model: str = ANTHROPIC_MODEL):
        if client is None:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.client = client
        self.model = model or ANTHROPIC_MODEL

    def generate(self, system, user, schema, effort="medium"):
        import anthropic

        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system,
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.APIError as e:
            self.last_error = f"Anthropic error: {getattr(e, 'message', e)}"
            return None
        if response.stop_reason in ("refusal", "max_tokens"):
            self.last_error = f"Claude stopped early ({response.stop_reason})"
            return None
        return _parse(self, "".join(b.text for b in response.content if b.type == "text"), schema)


class OpenAICompatWriter(Writer):
    """Chat Completions over plain HTTP; works with any OpenAI-compatible endpoint."""

    def __init__(self, base_url: str, api_key: str, model: str, name: str = "ai", _open=None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.name = name
        self._open = _open or urllib.request.urlopen

    def generate(self, system, user, schema, effort="medium"):
        instructions = (system + "\n\nReply with ONLY a JSON object (no markdown, no commentary) "
                        "that matches this JSON Schema:\n" + json.dumps(schema))
        body = {"model": self.model,
                "messages": [{"role": "system", "content": instructions},
                             {"role": "user", "content": user}],
                "response_format": {"type": "json_object"}}
        data = self._post(body)
        if data is None and self.last_error and "response_format" in self.last_error.lower():
            body.pop("response_format")  # some servers don't support JSON mode
            data = self._post(body)
        if data is None:
            return None
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            self.last_error = "Unexpected response from the AI provider"
            return None
        return _parse(self, text, schema)

    def _post(self, body: dict) -> dict | None:
        headers = {"Content-Type": "application/json", "User-Agent": "Hala/0.1"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if "openrouter.ai" in self.base_url:
            headers["X-Title"] = "Hala"
        req = urllib.request.Request(f"{self.base_url}/chat/completions",
                                     data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with self._open(req, timeout=120) as resp:
                self.last_error = None
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            self.last_error = f"{self.name} error {e.code}: {_error_text(e)}"
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            self.last_error = f"Couldn't reach {self.name}: {e}"
        return None


def _error_text(e: urllib.error.HTTPError) -> str:
    try:
        raw = e.read().decode("utf-8", "replace")
        data = json.loads(raw)
        if isinstance(data, list) and data:
            data = data[0]
        err = data.get("error", data) if isinstance(data, dict) else data
        msg = err.get("message") if isinstance(err, dict) else str(err)
        return (msg or raw)[:300]
    except Exception:
        return e.reason if isinstance(e.reason, str) else "request failed"


def _parse(writer: Writer, text: str, schema: dict) -> dict | None:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    if not text.startswith("{") and "{" in text:
        text = text[text.index("{"): text.rindex("}") + 1]
    try:
        data = json.loads(text)
    except ValueError:
        writer.last_error = "The AI didn't return valid JSON"
        return None
    if not isinstance(data, dict) or any(k not in data for k in schema.get("required", [])):
        writer.last_error = "The AI's answer was missing required fields"
        return None
    for key, spec in schema.get("properties", {}).items():
        expected = {"string": str, "array": list}.get(spec.get("type"))
        if expected and key in data and not isinstance(data[key], expected):
            writer.last_error = f"The AI returned the wrong type for '{key}'"
            return None
    return data


def writer_from_settings(settings: dict) -> Writer | None:
    """Build the writer chosen in Settings, or None when AI is off or not configured."""
    if settings.get("use_ai") != "1":
        return None
    provider = settings.get("ai_provider") or "anthropic"
    spec = PROVIDERS.get(provider)
    if spec is None:
        return None
    key = settings.get(key_setting(provider), "")
    model = (settings.get("ai_model") or "").strip() or spec["model"]
    if provider == "anthropic":
        return AnthropicWriter(api_key=key, model=model) if key else None
    base_url = (settings.get("ai_base_url") or "").strip() if provider == "custom" else spec["base_url"]
    if not base_url or not model or (provider != "custom" and not key):
        return None
    return OpenAICompatWriter(base_url, key, model, name=provider)


TEST_SCHEMA = {"type": "object", "properties": {"greeting": {"type": "string"}},
               "required": ["greeting"], "additionalProperties": False}


def test_writer(writer: Writer) -> tuple[bool, str]:
    data = writer.generate("You are a helpful assistant.",
                           'Say hello to a small business owner in Taglish. Reply as {"greeting": "..."}.',
                           TEST_SCHEMA, effort="low")
    if data:
        return True, data["greeting"]
    return False, writer.last_error or "No answer from the AI provider"
