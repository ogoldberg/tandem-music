"""Request guards for Tandem's public routes: per-client rate limits and body-size caps.

Rate-limit state lives in a shared store so the limit holds across Vercel
serverless instances, whose in-process memory is not shared or persistent:

- Upstash Redis (REST API) when ``UPSTASH_REDIS_REST_URL``/``UPSTASH_REDIS_REST_TOKEN``
  (or the Vercel KV names ``KV_REST_API_URL``/``KV_REST_API_TOKEN``) are set.
- In-process memory only when NOT running on Vercel (local development), where a
  single process serves every request.
- On Vercel without a configured store, limited routes fail closed with 503 rather
  than run unlimited. A store error also fails closed.
"""
from __future__ import annotations

import ipaddress
import json
import math
import os
import threading
import time
from typing import Awaitable, Callable

import httpx

AUDIO_PATHS = frozenset({"/api/analyze", "/api/tune"})
CHAT_PATH = "/api/chat"
AUDIO_BODY_MAX_BYTES = 18_000_000
CHAT_BODY_MAX_BYTES = 262_144
# DESK.2: the Mac app's own window (a request tandem_desktop.guarded_app has checked and marked
# local) may send up to 10 minutes of 96 kHz stereo 16-bit WAV in one request.
LOCAL_AUDIO_BODY_MAX_BYTES = 240_000_000


def is_local(scope) -> bool:
    """Whether tandem_desktop.guarded_app checked this request's launch secret. Nothing else
    sets this scope key, so the hosted app never lifts its limits."""
    return scope.get("tandem_local") is True


class RateLimitUnavailable(Exception):
    """The shared rate-limit store is missing or failed; callers fail closed."""


def audio_limit() -> tuple[int, int]:
    """(max requests, window seconds) per client for the shared audio bucket."""
    limit = int(os.getenv("TANDEM_AUDIO_RATE_LIMIT", "20"))
    window = int(os.getenv("TANDEM_AUDIO_RATE_WINDOW_SECONDS", "60"))
    if limit < 1 or window < 1:
        raise ValueError("TANDEM_AUDIO_RATE_LIMIT and TANDEM_AUDIO_RATE_WINDOW_SECONDS must be >= 1")
    return limit, window


class MemoryStore:
    """Fixed-window counter for a single process. Local development only."""

    def __init__(self) -> None:
        self._counts: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    async def hit(self, key: str, window: int) -> int:
        now = time.time()
        with self._lock:
            for k in [k for k, (_, exp) in self._counts.items() if exp <= now]:
                del self._counts[k]
            count, expires = self._counts.get(key, (0, now + window))
            count += 1
            self._counts[key] = (count, expires)
            return count


class UpstashStore:
    """Fixed-window counter in Upstash Redis via its REST pipeline endpoint."""

    def __init__(self, url: str, token: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.transport = transport

    async def hit(self, key: str, window: int) -> int:
        commands = [["INCR", key], ["EXPIRE", key, str(window + 1)]]
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(3.0), transport=self.transport) as client:
                r = await client.post(self.url + "/pipeline", headers={"authorization": "Bearer " + self.token}, json=commands)
                r.raise_for_status()
                results = r.json()
            first = results[0]
            if "error" in first:
                raise RateLimitUnavailable("rate-limit store error: " + str(first["error"])[:200])
            return int(first["result"])
        except RateLimitUnavailable:
            raise
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise RateLimitUnavailable("rate-limit store request failed: " + type(exc).__name__) from exc


_memory_store = MemoryStore()
# Tests may inject an httpx transport for the Upstash store.
upstash_transport: httpx.AsyncBaseTransport | None = None


def resolve_store():
    url = os.getenv("UPSTASH_REDIS_REST_URL") or os.getenv("KV_REST_API_URL") or ""
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN") or os.getenv("KV_REST_API_TOKEN") or ""
    if url and token:
        return UpstashStore(url, token, upstash_transport)
    if os.getenv("VERCEL"):
        raise RateLimitUnavailable("rate limiting needs UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN on Vercel")
    return _memory_store


def reset_memory_store() -> None:
    global _memory_store
    _memory_store = MemoryStore()


def client_id(scope) -> str:
    """Rate-limit key for the client. On Vercel the platform overwrites
    x-forwarded-for with the real client address, so it is trusted there;
    elsewhere it is caller-controlled and the socket address is used. IPv6
    clients are keyed by their /64, since one host usually controls a whole /64."""
    address = ""
    if os.getenv("VERCEL"):
        for name, value in scope.get("headers") or []:
            if name == b"x-forwarded-for":
                address = value.decode("latin-1").split(",")[0].strip()
                break
    if not address:
        client = scope.get("client")
        address = client[0] if client else "unknown"
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return address[:64]
    if ip.version == 6:
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def _json_response(status: int, detail: str, extra_headers: list[tuple[bytes, bytes]] | None = None):
    body = json.dumps({"detail": detail}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    headers += extra_headers or []
    return body, headers, status


class _BodyTooLarge(Exception):
    pass


class RequestGuardMiddleware:
    """ASGI middleware: rate-limits audio routes, then caps request body size
    for audio routes and /api/chat (checked on Content-Length and while streaming).
    Requests from the Mac app's own window (is_local) are not rate-limited and may send
    longer audio."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if path in AUDIO_PATHS:
            if is_local(scope):
                max_bytes = LOCAL_AUDIO_BODY_MAX_BYTES
            else:
                max_bytes = AUDIO_BODY_MAX_BYTES
                blocked = await self._rate_limit(scope)
                if blocked:
                    return await self._send(send, *blocked)
        elif path == CHAT_PATH:
            max_bytes = CHAT_BODY_MAX_BYTES
        else:
            return await self.app(scope, receive, send)

        for name, value in scope.get("headers") or []:
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    return await self._send(send, *_json_response(400, "Invalid Content-Length"))
                if declared > max_bytes:
                    return await self._send(send, *_json_response(413, f"Request body over {max_bytes} bytes"))

        received = 0
        overflow = False

        async def limited_receive():
            nonlocal received, overflow
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_bytes:
                    overflow = True
                    raise _BodyTooLarge()
            return message

        started = False

        async def guarded_send(message):
            nonlocal started
            if overflow:
                return  # the 413 below replaces whatever the app tried to send
            started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _BodyTooLarge:
            overflow = True
        except Exception:
            if not overflow:
                raise
        if overflow and not started:
            await self._send(send, *_json_response(413, f"Request body over {max_bytes} bytes"))

    async def _rate_limit(self, scope):
        try:
            limit, window = audio_limit()
            store = resolve_store()
            window_index = math.floor(time.time() / window)
            key = f"tandem:rl:audio:{client_id(scope)}:{window_index}"
            count = await store.hit(key, window)
        except (RateLimitUnavailable, ValueError) as exc:
            return _json_response(503, "Rate limiting unavailable: " + str(exc))
        if count > limit:
            retry_after = max(1, int((window_index + 1) * window - time.time()))
            return _json_response(429, f"Too many audio requests; limit is {limit} per {window} seconds",
                                  [(b"retry-after", str(retry_after).encode())])
        return None

    @staticmethod
    async def _send(send, body: bytes, headers, status: int):
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
