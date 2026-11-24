"""Tests for the Groq backup: OpenRouter rate limit -> Groq answers."""
import json

from app import http_client
from app.embeddings import RateLimitError
from app.llm import FallbackLLM, GroqLLM, get_llm


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)
        self.headers = {}

    def json(self):
        return self._payload


def _chat_payload(content):
    return {"choices": [{"message": {"content": content}}]}


def test_get_llm_returns_fallback_when_both_keys_set(monkeypatch):
    from app.config import settings

    # Rule-based mode must be off here, or it overrides the provider chain.
    monkeypatch.setattr(settings, "review_fallback", "")
    monkeypatch.setattr(settings, "openrouter_api_key", "or-key")
    monkeypatch.setattr(settings, "groq_api_key", "groq-key")
    llm = get_llm()
    assert isinstance(llm, FallbackLLM)
    assert isinstance(llm.primary, object)
    assert isinstance(llm.backup, GroqLLM)


def test_fallback_llm_uses_backup_on_rate_limit():
    class Primary:
        def complete_json(self, messages):
            raise RateLimitError("OpenRouter rate limit reached.")

        def stream(self, messages):
            raise RateLimitError("OpenRouter rate limit reached.")
            yield  # pragma: no cover - makes this a generator

    class Backup:
        def complete_json(self, messages):
            return {"items": []}

        def stream(self, messages):
            yield "backup answer"

    llm = FallbackLLM(Primary(), Backup())
    assert llm.complete_json([]) == {"items": []}
    assert llm.fallback_used is True
    assert "".join(llm.stream([])) == "backup answer"


def test_fallback_llm_does_not_switch_after_first_token():
    class Primary:
        def complete_json(self, messages):
            return {"items": []}

        def stream(self, messages):
            yield "partial "
            raise RateLimitError("late rate limit")

    class Backup:
        def stream(self, messages):
            yield "backup"

    llm = FallbackLLM(Primary(), Backup())
    try:
        "".join(llm.stream([]))
        raise AssertionError("expected RateLimitError")
    except RateLimitError:
        pass
    assert llm.fallback_used is False


def test_groq_llm_posts_to_groq_url(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["model"] = kwargs["json"]["model"]
        return _FakeResp(200, _chat_payload('{"items": []}'))

    monkeypatch.setattr(http_client, "post", fake_post)
    llm = GroqLLM(api_key="groq-key")
    assert llm.complete_json([{"role": "user", "content": "hi"}]) == {"items": []}
    assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert seen["model"] == "qwen/qwen3.8-27b"


def test_complete_json_retries_on_rate_limit(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            return _FakeResp(429, {"error": {"message": "rate limited"}})
        return _FakeResp(200, _chat_payload('{"items": []}'))

    monkeypatch.setattr(http_client, "post", fake_post)
    monkeypatch.setattr("app.llm.time.sleep", lambda s: None)
    llm = GroqLLM(api_key="groq-key")
    assert llm.complete_json([{"role": "user", "content": "hi"}]) == {"items": []}
    assert calls["n"] == 3


def test_complete_json_gives_up_after_retries(monkeypatch):
    def fake_post(url, **kwargs):
        return _FakeResp(429, {"error": {"message": "rate limited"}})

    monkeypatch.setattr(http_client, "post", fake_post)
    monkeypatch.setattr("app.llm.time.sleep", lambda s: None)
    llm = GroqLLM(api_key="groq-key")
    try:
        llm.complete_json([{"role": "user", "content": "hi"}])
        raise AssertionError("expected RateLimitError")
    except RateLimitError:
        pass


def test_rule_based_wins_over_gemini_key(monkeypatch):
    """REVIEW_FALLBACK=rule_based is an explicit override: it must win
    over a live Gemini key, or the 'no-key' eval run calls the live API."""
    from app.config import settings
    from app.llm import RuleBasedLLM

    monkeypatch.setattr(settings, "gemini_api_key", "gem-key")
    monkeypatch.setattr(settings, "review_fallback", "rule_based")
    assert isinstance(get_llm(), RuleBasedLLM)


def test_get_embedder_raises_without_key(monkeypatch):
    """No OpenRouter key and no rule-based mode: fail loudly instead of
    silently running the hash embedder in production."""
    import pytest

    from app.config import settings
    from app.embeddings import AIError, get_embedder

    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "review_fallback", "")
    with pytest.raises(AIError):
        get_embedder()


def test_get_embedder_uses_hash_in_rule_based_mode(monkeypatch):
    """The rule-based eval/dev mode is the only case that gets the hash stand-in."""
    from app.config import settings
    from app.embeddings import HashEmbedder, get_embedder

    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "review_fallback", "rule_based")
    assert isinstance(get_embedder(), HashEmbedder)
