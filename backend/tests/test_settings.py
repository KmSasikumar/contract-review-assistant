"""Tests for the Settings page: GET/PUT /api/settings and the per-user LLM."""
from app.llm import DEFAULT_MODEL, DEFAULT_PROVIDER, FallbackLLM, GeminiLLM, get_llm_for_user
from app.models import UserSettings


def test_get_settings_returns_gemini_default(client, db):
    data = client.get("/api/settings").json()
    assert data["chat_provider"] == DEFAULT_PROVIDER == "gemini"
    assert data["chat_model"] == DEFAULT_MODEL == "gemini-2.5-flash"
    assert any(o["model"] == "gemini-2.5-flash" for o in data["options"])
    assert any(o["provider"] == "openrouter" for o in data["options"])
    assert any(o["provider"] == "groq" for o in data["options"])


def test_put_settings_saves_and_get_returns_it(client, db):
    resp = client.put(
        "/api/settings",
        json={
            "chat_provider": "openrouter",
            "chat_model": "google/gemma-4-31b-it:free",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["chat_provider"] == "openrouter"
    assert resp.json()["chat_model"] == "google/gemma-4-31b-it:free"
    # A second GET returns the saved choice, not the default.
    assert client.get("/api/settings").json()["chat_model"] == "google/gemma-4-31b-it:free"


def test_put_settings_rejects_unknown_model(client, db):
    resp = client.put(
        "/api/settings",
        json={"chat_provider": "gemini", "chat_model": "gemini-99-ultra"},
    )
    assert resp.status_code == 400
    # The default is untouched after a rejected save.
    assert client.get("/api/settings").json()["chat_model"] == DEFAULT_MODEL


def test_get_llm_for_user_uses_saved_choice(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "gemini_api_key", "gemini-key")
    db.add(UserSettings(user_id="user-a", chat_provider="gemini", chat_model="gemini-2.5-pro"))
    db.commit()
    llm = get_llm_for_user(db, "user-a")
    assert isinstance(llm, FallbackLLM)
    assert isinstance(llm.primary, GeminiLLM)
    assert llm.primary.model == "gemini-2.5-pro"


def test_get_llm_for_user_falls_back_when_no_setting(db):
    # No row saved: the env-based chain (rule_based stand-in in tests).
    llm = get_llm_for_user(db, "user-a")
    assert llm.__class__.__name__ == "RuleBasedLLM"


def test_get_llm_for_user_falls_back_when_provider_key_missing(db):
    # A saved Gemini choice with no Gemini key must not break reviews.
    db.add(UserSettings(user_id="user-a", chat_provider="gemini", chat_model="gemini-2.5-flash"))
    db.commit()
    llm = get_llm_for_user(db, "user-a")
    assert llm.__class__.__name__ == "RuleBasedLLM"


def test_health_endpoint_responds(client):
    # Regression test (24 Nov 2026): main.py imported the settings ROUTER
    # under the name `settings`, shadowing the config Settings object, so
    # /api/health raised AttributeError and returned 500 on the live app.
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert isinstance(data["ai_configured"], bool)
    assert isinstance(data["auth_configured"], bool)


def test_health_reports_ai_configured_when_gemini_key_set(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "gemini_api_key", "gemini-key")
    data = client.get("/api/health").json()
    assert data["ai_configured"] is True
