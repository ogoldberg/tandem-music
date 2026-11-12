"""AI.4: the person's own AI provider, model and key in the Mac app (tandem_desktop/ai_keys.py).

The provider and model are kept in ai.json, the key only in the macOS Keychain. These tests use a
stand-in key store (CI runs on Linux, which has no Keychain) and stand-in providers (no paid API is
called); one test uses the real Keychain on a Mac."""
import asyncio
import json
import logging
import sys
import uuid

import httpx
import pytest

import tandem_backend as server
import tandem_desktop as desk
from tandem_desktop import ai_keys

PORT = 47998
Client = httpx.AsyncClient  # the stand-in provider replaces httpx.AsyncClient for the server only
SECRET = "s" * 43
KEY = "sk-test-0123456789abcdef"
PROJECT = {"bpm": 96, "instrument": "piano", "melody_locked": True, "notes": [{"m": 60, "t": 0, "d": 0.5}], "drums": []}


class MemoryKeys:
    """Stands in for the Keychain: one secret per provider."""

    def __init__(self):
        self.items = {}

    def get(self, provider):
        return self.items.get(provider)

    def set(self, provider, key):
        self.items[provider] = key

    def delete(self, provider):
        self.items.pop(provider, None)


@pytest.fixture
def clean_env(monkeypatch):
    for key in ("TANDEM_PROVIDER", "TANDEM_MODEL", "TANDEM_API_KEY", "TANDEM_BASE_URL", "TANDEM_ACCESS_TOKEN", "VERCEL"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def settings(tmp_path, clean_env):
    return ai_keys.AISettings(tmp_path, MemoryKeys())


@pytest.fixture
def provider(monkeypatch):
    """A stand-in AI provider: records each request and answers with the edit plan in `reply`."""
    seen = []
    state = {"reply": {"reply": "Raised it and sped it up.", "actions": [{"type": "transpose", "semitones": 2}, {"type": "set_tempo", "bpm": 120}]},
             "status": 200}

    def handler(request):
        seen.append(request)
        if state["status"] != 200:
            return httpx.Response(state["status"], text="unauthorized")
        text = json.dumps(state["reply"])
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"content": [{"type": "text", "text": text}]})
        if ":generateContent" in request.url.path:
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    actual = Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(server.httpx, "AsyncClient", lambda **kwargs: actual(transport=transport, **kwargs) if "transport" not in kwargs else actual(**kwargs))
    return {"seen": seen, "state": state}


def call(settings, method, path, secret=SECRET, **kw):
    app = desk.guarded_app(PORT, SECRET, ai_settings=settings)
    headers = {**kw.pop("headers", {}), **({desk.LAUNCH_HEADER: secret} if secret else {})}

    async def go():
        async with Client(transport=httpx.ASGITransport(app=app), base_url=f"http://127.0.0.1:{PORT}") as c:
            return await c.request(method, path, headers=headers, **kw)
    return asyncio.run(go())


def save(settings, **body):
    return call(settings, "PUT", "/api/desktop/ai", json=body)


def chat(settings, message="Make it brighter", project=PROJECT):
    return call(settings, "POST", "/api/chat", json={"message": message, "project": project})


def test_the_key_goes_to_the_key_store_and_never_back_to_the_page(settings, tmp_path):
    r = save(settings, provider="openai", model="gpt-test", key=KEY)
    assert r.status_code == 200, r.text
    assert settings.keys.items == {"openai": KEY}
    assert json.loads((tmp_path / "ai.json").read_text()) == {"provider": "openai", "model": "gpt-test"}
    page = call(settings, "GET", "/api/desktop/ai")
    for answer in (r, page):
        assert KEY not in answer.text
        assert answer.headers["cache-control"] == "no-store"
    assert page.json()["provider"] == "openai" and page.json()["has_key"] is True and page.json()["ready"] is True
    config = call(settings, "GET", "/api/config").json()
    assert (config["provider"], config["model"], config["ai_ready"], config["ai_source"]) == ("openai-compatible", "gpt-test", True, "your-settings")
    assert KEY not in json.dumps(config)


def test_changing_the_model_keeps_the_saved_key(settings):
    save(settings, provider="anthropic", model="first-model", key=KEY)
    assert save(settings, provider="anthropic", model="second-model").json()["has_key"] is True
    assert settings.keys.items == {"anthropic": KEY}


@pytest.mark.parametrize("name,host,path,auth", [
    ("openai", "api.openai.com", "/v1/chat/completions", ("authorization", "Bearer " + KEY)),
    ("openrouter", "openrouter.ai", "/api/v1/chat/completions", ("authorization", "Bearer " + KEY)),
    ("anthropic", "api.anthropic.com", "/v1/messages", ("x-api-key", KEY)),
    ("gemini", "generativelanguage.googleapis.com", "/v1beta/models/test-model:generateContent", ("x-goog-api-key", KEY)),
])
def test_an_edit_uses_the_saved_provider_model_and_key_and_melody_lock_still_holds(settings, provider, name, host, path, auth):
    save(settings, provider=name, model="test-model", key=KEY)
    r = chat(settings)
    assert r.status_code == 200, r.text
    # Melody lock (on in PROJECT) removed the transpose; the tempo change came through.
    assert r.json() == {"reply": "Raised it and sped it up.", "actions": [{"type": "set_tempo", "bpm": 120}]}
    request = provider["seen"][0]
    assert (request.url.host, request.url.path) == (host, path)
    assert request.headers[auth[0]] == auth[1]
    body = json.loads(request.content)
    assert body.get("model", "test-model") == "test-model"


def test_with_melody_lock_off_the_melody_edit_applies(settings, provider):
    save(settings, provider="openai", model="test-model", key=KEY)
    r = chat(settings, project={**PROJECT, "melody_locked": False})
    assert {"type": "transpose", "semitones": 2} in r.json()["actions"]


def test_ollama_needs_no_key_and_refuses_one(settings, provider):
    assert save(settings, provider="ollama", model="llama3.2").json()["ready"] is True
    r = chat(settings)
    assert r.status_code == 200 and provider["seen"][0].url == "http://localhost:11434/v1/chat/completions"
    assert "authorization" not in provider["seen"][0].headers
    r = save(settings, provider="ollama", model="llama3.2", key=KEY)
    assert r.status_code == 400 and "needs no key" in r.text and settings.keys.items == {}


def test_another_openai_compatible_server_gets_its_address_and_an_optional_key(settings, provider):
    r = save(settings, provider="custom", model="local-model", base_url="http://localhost:1234/v1/")
    assert r.status_code == 200 and r.json()["ready"] is True and r.json()["base_url"] == "http://localhost:1234/v1"
    assert chat(settings).status_code == 200
    assert provider["seen"][0].url == "http://localhost:1234/v1/chat/completions"
    for bad in ("ftp://host/v1", "http://user:pw@host/v1", "localhost:1234", "http://host/v1?x=1"):
        assert save(settings, provider="custom", model="m", base_url=bad).status_code == 400


def test_without_the_key_the_edit_is_refused_and_says_what_to_do(settings, provider):
    save(settings, provider="openai", model="test-model")
    r = chat(settings)
    assert r.status_code == 503 and "Add your OpenAI key" in r.text and provider["seen"] == []
    config = call(settings, "GET", "/api/config").json()
    assert config["ai_ready"] is False and "Add your OpenAI key" in config["ai_problem"]


def test_with_nothing_saved_the_window_is_told_to_choose_a_provider(settings, provider):
    r = chat(settings)
    assert r.status_code == 503 and "Choose your AI provider" in r.text and provider["seen"] == []


def test_with_nothing_saved_the_servers_own_configuration_still_works(settings, provider, monkeypatch):
    monkeypatch.setenv("TANDEM_MODEL", "env-model")
    monkeypatch.setenv("TANDEM_API_KEY", "env-key")
    assert chat(settings).status_code == 200
    assert provider["seen"][0].headers["authorization"] == "Bearer env-key"
    assert call(settings, "GET", "/api/config").json()["ai_source"] == "server"


def test_saved_settings_win_over_the_servers_configuration(settings, provider, monkeypatch):
    monkeypatch.setenv("TANDEM_MODEL", "env-model")
    monkeypatch.setenv("TANDEM_API_KEY", "env-key")
    save(settings, provider="openai", model="mine", key=KEY)
    chat(settings)
    assert provider["seen"][0].headers["authorization"] == "Bearer " + KEY
    assert json.loads(provider["seen"][0].content)["model"] == "mine"


def test_forgetting_the_key_removes_it_from_the_key_store(settings):
    save(settings, provider="gemini", model="test-model", key=KEY)
    r = call(settings, "DELETE", "/api/desktop/ai/key")
    assert r.status_code == 200 and r.json()["has_key"] is False and r.json()["ready"] is False
    assert settings.keys.items == {}


def test_a_failed_provider_call_does_not_echo_the_key(settings, provider, caplog):
    provider["state"]["status"] = 401
    save(settings, provider="openrouter", model="test-model", key=KEY)
    with caplog.at_level(logging.DEBUG):
        r = chat(settings)
    assert r.status_code == 502 and "AI provider request failed" in r.text
    assert KEY not in r.text and KEY not in caplog.text


@pytest.mark.parametrize("body,message", [
    ({"provider": "nope", "model": "m"}, "listed providers"),
    ({"provider": "openai", "model": ""}, "Name the model"),
    ({"provider": "openai", "model": "bad model"}, "Name the model"),
    ({"provider": "openai", "model": "m", "key": "has space"}, "no spaces"),
    ({"provider": "openai", "model": "m", "key": "k" * 513}, "up to 512"),
    ({"provider": "openai", "model": "m", "extra": 1}, "Send the provider"),
])
def test_unusable_settings_are_refused_and_nothing_is_saved(settings, tmp_path, body, message):
    r = save(settings, **body)
    assert r.status_code == 400 and message in r.text
    assert settings.keys.items == {} and not (tmp_path / "ai.json").exists()


def test_a_damaged_settings_file_is_explained(settings, tmp_path, provider):
    (tmp_path / "ai.json").write_text("{not json")
    r = chat(settings)
    assert r.status_code == 503 and "is damaged" in r.text and provider["seen"] == []
    r = call(settings, "GET", "/api/desktop/ai")
    # The choices are still listed so the panel can save over the damaged file.
    assert r.status_code == 200 and "is damaged" in r.json()["problem"] and len(r.json()["providers"]) == len(ai_keys.PROVIDERS)
    assert r.json()["provider"] is None and r.json()["ready"] is False
    r = save(settings, provider="openai", model="m", key=KEY)
    assert r.status_code == 200 and r.json()["problem"] is None and r.json()["ready"] is True


def test_a_key_saved_for_one_server_is_never_sent_to_another(settings, provider):
    save(settings, provider="custom", model="m", base_url="https://first.example/v1", key=KEY)
    assert settings.keys.items == {"custom https://first.example/v1": KEY}
    r = save(settings, provider="custom", model="m", base_url="http://localhost:1234/v1")
    assert r.json()["has_key"] is False and r.json()["ready"] is True
    assert settings.llm_config()["key"] == "" and settings.keys.items == {}
    assert chat(settings).status_code == 200
    assert provider["seen"][0].url == "http://localhost:1234/v1/chat/completions"
    assert "authorization" not in provider["seen"][0].headers


def test_another_providers_key_is_kept_when_switching_to_a_server(settings):
    save(settings, provider="openai", model="m", key=KEY)
    save(settings, provider="custom", model="m", base_url="http://localhost:1234/v1")
    assert settings.llm_config()["key"] == ""
    assert save(settings, provider="openai", model="m").json()["has_key"] is True


def test_the_same_server_address_written_differently_keeps_its_key(settings):
    save(settings, provider="custom", model="m", base_url="https://First.Example/v1/", key=KEY)
    save(settings, provider="custom", model="m", base_url="https://first.example/v1")
    assert settings.llm_config()["key"] == KEY


def test_the_routes_need_the_launch_secret_and_the_right_method(settings):
    assert call(settings, "GET", "/api/desktop/ai", secret=None).status_code == 403
    assert call(settings, "PUT", "/api/desktop/ai", secret="t" * 43, json={"provider": "openai", "model": "m", "key": KEY}).status_code == 403
    assert call(settings, "POST", "/api/desktop/ai", json={}).status_code == 405
    assert call(settings, "GET", "/api/desktop/ai/other").status_code == 404
    assert settings.keys.items == {}


def test_an_oversized_body_is_refused(settings):
    r = call(settings, "PUT", "/api/desktop/ai", content=b"{" + b" " * 5000 + b"}", headers={"content-type": "application/json"})
    assert r.status_code == 400 and "too large" in r.text


def test_the_hosted_app_has_no_settings_routes_and_ignores_saved_settings(settings, provider, monkeypatch):
    save(settings, provider="openai", model="mine", key=KEY)
    monkeypatch.setenv("TANDEM_MODEL", "env-model")
    monkeypatch.setenv("TANDEM_API_KEY", "env-key")

    async def go():
        async with Client(transport=httpx.ASGITransport(app=server.app), base_url="http://testserver") as c:
            return (await c.get("/api/desktop/ai"), await c.post("/api/chat", json={"message": "hi", "project": PROJECT}))
    routes, answer = asyncio.run(go())
    assert routes.status_code == 404 and answer.status_code == 200
    assert provider["seen"][0].headers["authorization"] == "Bearer env-key"
    # A scope that claims saved settings but is not marked local (only guarded_app marks it) is ignored.
    from starlette.requests import Request
    assert server.llm_config(Request({"type": "http", "tandem_ai": settings, "headers": []}))["source"] == "server"


@pytest.mark.skipif(sys.platform != "darwin", reason="the macOS Keychain exists only on a Mac")
def test_the_real_keychain_keeps_reads_and_forgets_the_key(tmp_path, clean_env):
    keyring = pytest.importorskip("keyring")
    keys = ai_keys.KeychainKeys(service="Tandem AI key test " + uuid.uuid4().hex)
    settings = ai_keys.AISettings(tmp_path, keys)
    try:
        settings.save({"provider": "openai", "model": "gpt-test", "key": KEY})
        assert keyring.get_password(keys.service, "openai") == KEY
        assert settings.llm_config()["key"] == KEY
        assert KEY not in (tmp_path / "ai.json").read_text()
        settings.forget_key()
        assert keyring.get_password(keys.service, "openai") is None
    finally:
        keys.delete("openai")
