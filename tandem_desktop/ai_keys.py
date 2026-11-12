"""AI.4: the person's own AI provider, model and key in the Mac app.

The provider and model are kept in <home>/ai.json next to desktop.json. The key is kept only in the
macOS Keychain (service "Tandem AI key", one item per provider; for another OpenAI-compatible server
one item per server address, so a key is only ever sent to the address it was saved for), read by
the local server when it calls the provider, and never written to ai.json, a project, a log or the page: the page is told
only whether a key is saved. /api/chat in the app's own window uses these settings through
`llm_config()` (guarded_app passes this object to the hosted app as scope["tandem_ai"]), so the
existing invoke_llm, normalize_actions and melody lock apply unchanged. Nothing here imports
keyring until the Keychain is used, so CI can test it on Linux with a stand-in key store.
"""
import json
import os
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit

import anyio

SETTINGS_FILE = "ai.json"
KEYCHAIN_SERVICE = "Tandem AI key"
SETTINGS_PATH = "/api/desktop/ai"
KEY_PATH = "/api/desktop/ai/key"
MAX_BODY = 4096
MAX_KEY = 512
MAX_MODEL = 200

# kind is the invoke_llm provider; base is where the requests go (empty: invoke_llm's default).
PROVIDERS = {
    "openai": {"label": "OpenAI", "kind": "openai-compatible", "base": "https://api.openai.com/v1", "key": True},
    "anthropic": {"label": "Anthropic", "kind": "anthropic", "base": "", "key": True},
    "gemini": {"label": "Google Gemini", "kind": "gemini", "base": "", "key": True},
    "openrouter": {"label": "OpenRouter", "kind": "openai-compatible", "base": "https://openrouter.ai/api/v1", "key": True},
    "ollama": {"label": "Ollama on this Mac", "kind": "ollama", "base": "http://localhost:11434/v1", "key": False},
    "custom": {"label": "Another OpenAI-compatible server", "kind": "openai-compatible", "base": None, "key": None},
}
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$")


class AISettingsError(ValueError):
    """Settings Tandem cannot use; the message says what is wrong."""


class KeychainKeys:
    """The keys in the macOS Keychain, through keyring (imported on first use)."""

    def __init__(self, service=KEYCHAIN_SERVICE):
        self.service = service

    def get(self, provider):
        import keyring
        return keyring.get_password(self.service, provider)

    def set(self, provider, key):
        import keyring
        keyring.set_password(self.service, provider, key)

    def delete(self, provider):
        import keyring
        from keyring.errors import PasswordDeleteError
        try:
            keyring.delete_password(self.service, provider)
        except PasswordDeleteError:
            pass


def _check_key(key):
    if not isinstance(key, str) or not key or len(key) > MAX_KEY or any(c.isspace() or ord(c) < 32 for c in key):
        raise AISettingsError("The key must be one line of up to 512 characters with no spaces.")
    return key


def _check_model(model):
    if not isinstance(model, str) or not 0 < len(model) <= MAX_MODEL or not MODEL_RE.match(model):
        raise AISettingsError("Name the model as your provider lists it, such as the id in its model list.")
    return model


def _check_base(base):
    if not isinstance(base, str) or len(base) > 300:
        raise AISettingsError("Give the server's address, such as http://localhost:1234/v1.")
    parts = urlsplit(base.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise AISettingsError("Give the server's address as http:// or https:// with no password, query or fragment, such as http://localhost:1234/v1.")
    return (parts.scheme + "://" + parts.netloc.lower() + parts.path).rstrip("/")


def _account(settings):
    """The Keychain item for these settings: the provider, or for another server its address too, so
    a key saved for one server is never sent to another."""
    if settings["provider"] == "custom":
        return "custom " + settings["base_url"]
    return settings["provider"]


class AISettings:
    """The saved provider and model, the Keychain key, and the /api/desktop/ai routes."""

    def __init__(self, home, keys=None):
        self.path = Path(home) / SETTINGS_FILE
        self.keys = keys if keys is not None else KeychainKeys()
        self._lock = threading.Lock()

    def load(self):
        """The saved settings ({"provider", "model", "base_url"}), or None when nothing is saved."""
        if not self.path.exists():
            return None
        try:
            saved = json.loads(self.path.read_text())
            provider = saved["provider"]
            if provider not in PROVIDERS:
                raise KeyError(provider)
            settings = {"provider": provider, "model": _check_model(saved["model"])}
            if provider == "custom":
                settings["base_url"] = _check_base(saved["base_url"])
            return settings
        except (ValueError, KeyError, TypeError) as exc:
            raise AISettingsError(f"{self.path} is damaged ({exc}). Choose the provider and model again to replace it.") from exc

    def _write(self, settings):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(settings))
        os.replace(tmp, self.path)

    def _needs_key(self, provider):
        need = PROVIDERS[provider]["key"]
        return need is True

    def public(self):
        """What the page may know: the choices, the saved provider and model, and whether a key is
        saved. Never the key. A damaged settings file is reported as `problem` with the choices
        still listed, so the page can save new settings over it."""
        problem = None
        try:
            settings = self.load()
        except AISettingsError as exc:
            settings, problem = None, str(exc)
        has_key = bool(settings and self.keys.get(_account(settings)))
        return {"providers": [{"id": k, "label": v["label"], "needs_key": v["key"]} for k, v in PROVIDERS.items()],
                "problem": problem,
                "provider": settings["provider"] if settings else None,
                "model": settings["model"] if settings else None,
                "base_url": settings.get("base_url") if settings else None,
                "has_key": has_key,
                "ready": bool(settings) and (has_key or not self._needs_key(settings["provider"]))}

    def save(self, body):
        """Save the provider and model; a key in the body goes to the Keychain only."""
        if not isinstance(body, dict) or set(body) - {"provider", "model", "base_url", "key"}:
            raise AISettingsError("Send the provider, the model and, if you are changing it, the key.")
        provider = body.get("provider")
        if provider not in PROVIDERS:
            raise AISettingsError("Choose one of the listed providers.")
        settings = {"provider": provider, "model": _check_model(body.get("model"))}
        if provider == "custom":
            settings["base_url"] = _check_base(body.get("base_url"))
        key = body.get("key")
        if key is not None and key != "":
            if PROVIDERS[provider]["key"] is False:
                raise AISettingsError(f"{PROVIDERS[provider]['label']} needs no key.")
            key = _check_key(key)
        with self._lock:
            try:
                before = self.load()
            except AISettingsError:
                before = None
            if key:
                self.keys.set(_account(settings), key)
            self._write(settings)
            # Moving to another server's address replaces the server: its old key is removed.
            if before and before["provider"] == provider == "custom" and _account(before) != _account(settings):
                self.keys.delete(_account(before))
        return self.public()

    def forget_key(self):
        settings = self.load()
        if settings:
            self.keys.delete(_account(settings))
        return self.public()

    def llm_config(self):
        """The provider configuration for invoke_llm, or None when nothing is saved (the server's
        own configuration then applies)."""
        settings = self.load()
        if settings is None:
            return None
        info = PROVIDERS[settings["provider"]]
        key = self.keys.get(_account(settings)) or ""
        if info["key"] is True and not key:
            raise AISettingsError(f"Add your {info['label']} key in Your AI settings to use {info['label']}.")
        return {"provider": info["kind"], "model": settings["model"], "key": key,
                "base_url": settings.get("base_url") or info["base"] or "", "label": info["label"]}

    async def __call__(self, scope, receive, send):
        path, method = scope.get("path", ""), scope.get("method", "")
        try:
            if path == SETTINGS_PATH and method == "GET":
                result = await anyio.to_thread.run_sync(self.public)
            elif path == SETTINGS_PATH and method == "PUT":
                body = await _read_json(scope, receive)
                result = await anyio.to_thread.run_sync(self.save, body)
            elif path == KEY_PATH and method == "DELETE":
                result = await anyio.to_thread.run_sync(self.forget_key)
            elif path in (SETTINGS_PATH, KEY_PATH):
                return await _reply(send, 405, b"Method not allowed")
            else:
                return await _reply(send, 404, b"Not found")
        except AISettingsError as exc:
            return await _reply(send, 400, str(exc).encode())
        except Exception as exc:  # the Keychain refused or failed; say so without any key material
            return await _reply(send, 500, f"The Keychain could not be used: {type(exc).__name__}".encode())
        return await _reply(send, 200, json.dumps(result).encode(), b"application/json")


async def _read_json(scope, receive):
    declared = [v for k, v in scope.get("headers", []) if k == b"content-length"]
    if declared and declared[0].isdigit() and int(declared[0]) > MAX_BODY:
        raise AISettingsError("The settings are too large.")
    parts, size = [], 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > MAX_BODY:
            raise AISettingsError("The settings are too large.")
        parts.append(chunk)
        if not message.get("more_body"):
            break
    try:
        return json.loads(b"".join(parts).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise AISettingsError("The settings could not be read.") from exc


async def _reply(send, status, body, content_type=b"text/plain; charset=utf-8"):
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", content_type), (b"content-length", str(len(body)).encode()),
                            (b"cache-control", b"no-store")]})
    await send({"type": "http.response.body", "body": body})
