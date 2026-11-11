"""DESK.1/DESK.2: the Mac app's launcher (tandem_desktop). These tests need no pywebview: they cover
the fixed port, the loopback-only server, the Host header check, the microphone permission rule,
the per-launch secret, the Origin check and the limits lifted for the app's own window."""
import asyncio
import io
import json
import socket
import wave

import httpx
import numpy as np
import pytest

import request_guards as guards
import tandem_desktop as desk

SECRET = desk.new_launch_secret()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_port_is_chosen_once_and_kept_across_launches(tmp_path):
    first = desk.load_port(tmp_path)
    assert json.loads((tmp_path / "desktop.json").read_text()) == {"port": first}
    # Even when the default port is now taken, the saved port is used: a different port would
    # be a different origin and hide the draft, versions and recordings.
    with socket.socket() as busy:
        try:
            busy.bind(("127.0.0.1", desk.DEFAULT_PORT))
        except OSError:
            pass
        assert desk.load_port(tmp_path) == first


def test_the_first_launch_avoids_a_busy_default_port(tmp_path, monkeypatch):
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        monkeypatch.setattr(desk, "DEFAULT_PORT", taken)
        port = desk.load_port(tmp_path)
    assert port != taken and 1024 <= port <= 65535
    assert desk.load_port(tmp_path) == port


def test_a_damaged_settings_file_is_reported_not_replaced(tmp_path):
    (tmp_path / "desktop.json").write_text("{not json")
    with pytest.raises(desk.DesktopError, match="desktop.json"):
        desk.load_port(tmp_path)
    (tmp_path / "desktop.json").write_text(json.dumps({"port": 80}))
    with pytest.raises(desk.DesktopError, match="port"):
        desk.load_port(tmp_path)
    assert json.loads((tmp_path / "desktop.json").read_text()) == {"port": 80}


def test_binding_a_port_in_use_says_tandem_may_already_be_running():
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        with pytest.raises(desk.DesktopError, match="already running"):
            desk.bind(busy.getsockname()[1])


def test_a_port_another_program_holds_on_all_interfaces_is_refused():
    # Issue #48: on macOS, SO_REUSEADDR let 127.0.0.1:<port> bind beside a 0.0.0.0:<port> listener.
    with socket.socket() as busy:
        busy.bind(("0.0.0.0", 0))
        busy.listen()
        with pytest.raises(desk.DesktopError, match="already running"):
            desk.bind(busy.getsockname()[1])


def test_the_server_binds_to_loopback_only():
    sock = desk.bind(free_port())
    try:
        assert sock.getsockname()[0] == "127.0.0.1"
    finally:
        sock.close()


@pytest.mark.parametrize("host,status", [
    ("127.0.0.1:{port}", 200),
    ("localhost:{port}", 421),
    ("127.0.0.1", 421),
    ("127.0.0.1:1", 421),
    ("evil.example:{port}", 421),
    ("", 421),
])
def test_only_the_apps_own_host_is_served(host, status):
    port = 47999
    app = desk.guarded_app(port, SECRET)
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            return await c.get("/api/health", headers={"host": host.format(port=port), desk.LAUNCH_HEADER: SECRET})
    r = asyncio.run(go())
    assert r.status_code == status
    if status == 421:
        assert r.text == "Unknown host"


def test_the_guard_also_refuses_requests_with_no_host_header():
    asyncio.run(_no_host_header())


async def _no_host_header():
    seen = []
    async def inner(scope, receive, send):
        seen.append(scope)
    app = desk.guarded_app(47999, SECRET, inner)
    sent = []
    async def send(message):
        sent.append(message)
    await app({"type": "http", "method": "GET", "path": "/", "headers": []}, None, send)
    assert not seen and sent[0]["status"] == 421
    # Lifespan events carry no headers and must reach the app.
    await app({"type": "lifespan"}, None, send)
    assert seen and seen[0]["type"] == "lifespan"


def test_the_microphone_is_granted_to_the_apps_own_page_only():
    allow = desk.allow_media
    assert allow("http", "127.0.0.1", 47000, desk.MEDIA_MICROPHONE, 47000)
    assert not allow("http", "127.0.0.1", 47000, desk.MEDIA_CAMERA, 47000)
    assert not allow("http", "127.0.0.1", 47000, desk.MEDIA_CAMERA_AND_MICROPHONE, 47000)
    assert not allow("http", "127.0.0.1", 47001, desk.MEDIA_MICROPHONE, 47000)
    assert not allow("http", "localhost", 47000, desk.MEDIA_MICROPHONE, 47000)
    assert not allow("https", "127.0.0.1", 47000, desk.MEDIA_MICROPHONE, 47000)


def test_the_launcher_server_serves_the_studio_and_refuses_foreign_hosts(tmp_path, monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    port = free_port()
    server, thread = desk.start_server(port, SECRET)
    try:
        base = f"http://127.0.0.1:{port}"
        page = httpx.get(base + "/")
        assert page.status_code == 200 and "<title>" in page.text
        config = httpx.get(base + "/api/config", headers={desk.LAUNCH_HEADER: SECRET}).json()
        assert config["runtime"] == "desktop"
        assert config["limits"] == {"analyze_seconds": 600, "tune_seconds": 600, "tune_notes": 4096}
        assert httpx.get(base + "/api/config").status_code == 403
        foreign = httpx.get(base + "/api/health", headers={"host": f"attacker.example:{port}", desk.LAUNCH_HEADER: SECRET})
        assert foreign.status_code == 421
    finally:
        desk.stop_server(server, thread)
    assert not thread.is_alive()
    with pytest.raises(httpx.ConnectError):
        httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=2)


def test_the_hosted_app_reports_the_web_runtime(monkeypatch):
    import tandem_backend
    monkeypatch.delenv("TANDEM_RUNTIME", raising=False)
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=tandem_backend.app), base_url="http://test") as c:
            return await c.get("/api/config")
    assert asyncio.run(go()).json()["runtime"] == "web"


# DESK.2: the per-launch secret, the Origin check and the lifted limits.

PORT = 47998
OWN = f"http://127.0.0.1:{PORT}"


@pytest.fixture
def local(monkeypatch):
    """Requests to the backend through the launcher's guard, as the Mac app's server runs it."""
    for name in ("VERCEL", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN", "KV_REST_API_URL",
                 "KV_REST_API_TOKEN", "TANDEM_ACCESS_TOKEN", "TANDEM_AUDIO_RATE_WINDOW_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TANDEM_AUDIO_RATE_LIMIT", "1")
    guards.reset_memory_store()
    app = desk.guarded_app(PORT, SECRET)

    def call(method, path, secret=SECRET, headers=None, guard=True, **kwargs):
        h = {"host": f"127.0.0.1:{PORT}", **(headers or {})}
        if secret is not None:
            h[desk.LAUNCH_HEADER] = secret
        import tandem_backend
        async def go():
            transport = httpx.ASGITransport(app=app if guard else tandem_backend.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.request(method, path, headers=h, **kwargs)
        return asyncio.run(go())
    return call


def wav(seconds, rate=16000, hz=220.0):
    t = np.arange(int(seconds * rate)) / rate
    x = (0.3 * np.sin(2 * np.pi * hz * t) * 32767).astype("<i2")
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(x.tobytes())
    return out.getvalue()


def test_api_requests_need_the_launch_secret_in_its_header(local):
    assert local("GET", "/api/health").status_code == 200
    for path in ("/api/health", "/api/config", "/api/chat", "/api/tune", "/api/analyze", "/api/nothing-here"):
        r = local("GET", path, secret=None)
        assert r.status_code == 403 and "own window" in r.text, path
    assert local("POST", "/api/analyze", secret=None, files={"file": ("a.wav", wav(1), "audio/wav")}).status_code == 403
    assert local("GET", "/api/health", secret="x" * 43).status_code == 403
    assert local("GET", "/api/health", secret=SECRET[:-1]).status_code == 403
    assert local("GET", "/api/health", secret="").status_code == 403


def test_the_launch_secret_is_accepted_only_in_the_header(local):
    assert local("GET", "/api/health?" + desk.LAUNCH_HEADER + "=" + SECRET, secret=None).status_code == 403
    assert local("GET", "/api/health", secret=None, headers={"cookie": desk.LAUNCH_HEADER + "=" + SECRET}).status_code == 403
    assert local("GET", "/api/health", secret=None, headers={"authorization": "Bearer " + SECRET}).status_code == 403


def test_two_launch_secret_headers_are_refused():
    app = desk.guarded_app(PORT, SECRET)
    sent = []
    async def send(message):
        sent.append(message)
    async def inner(scope, receive, send):
        raise AssertionError("must not reach the app")
    app = desk.guarded_app(PORT, SECRET, inner)
    headers = [(b"host", f"127.0.0.1:{PORT}".encode()), (b"x-tandem-launch", SECRET.encode()), (b"x-tandem-launch", SECRET.encode())]
    asyncio.run(app({"type": "http", "method": "GET", "path": "/api/health", "headers": headers}, None, send))
    assert sent[0]["status"] == 403


def test_the_page_and_its_files_load_without_the_secret(local):
    # Navigations and module imports cannot carry a header; they serve the same public code as the site.
    assert local("GET", "/", secret=None).status_code == 200
    assert local("GET", "/tuning.js", secret=None).status_code == 200


@pytest.mark.parametrize("origin", ["https://ogoldberg.github.io", "http://localhost:8000", "http://127.0.0.1:8000",
                                    f"http://127.0.0.1:{PORT + 1}", f"http://localhost:{PORT}", "null",
                                    f"https://127.0.0.1:{PORT}"])
def test_other_origins_get_no_cors_approval_and_no_answer(local, origin):
    preflight = local("OPTIONS", "/api/tune", headers={"origin": origin, "access-control-request-method": "POST",
                                                        "access-control-request-headers": desk.LAUNCH_HEADER})
    assert preflight.status_code == 403
    assert "access-control-allow-origin" not in preflight.headers
    # Even a simple request that needs no preflight, and even with the right secret.
    simple = local("POST", "/api/analyze?mode=rhythm", headers={"origin": origin}, files={"file": ("a.wav", wav(1), "audio/wav")})
    assert simple.status_code == 403
    assert "access-control-allow-origin" not in simple.headers
    assert local("GET", "/", secret=None, headers={"origin": origin}).status_code == 403


def test_the_apps_own_origin_is_served(local):
    r = local("POST", "/api/analyze?mode=rhythm", headers={"origin": OWN}, files={"file": ("a.wav", wav(1), "audio/wav")})
    assert r.status_code == 200


def test_the_hosted_cors_list_still_approves_its_origins(local):
    # Unchanged hosted behaviour: without the launcher's guard, the configured origins get approval.
    r = local("OPTIONS", "/api/tune", secret=None, guard=False, headers={
        "origin": "https://ogoldberg.github.io", "access-control-request-method": "POST"})
    assert r.headers.get("access-control-allow-origin") == "https://ogoldberg.github.io"


def test_the_apps_own_window_is_not_rate_limited(local):
    for _ in range(4):
        r = local("POST", "/api/analyze?mode=rhythm", files={"file": ("a.wav", wav(1), "audio/wav")})
        assert r.status_code == 200
    # The same backend without the launcher's mark keeps the hosted limit of 1 per window here.
    statuses = [local("POST", "/api/analyze?mode=rhythm", secret=None, guard=False,
                      files={"file": ("a.wav", wav(1), "audio/wav")}).status_code for _ in range(2)]
    assert statuses == [200, 429]


def test_a_spoofed_local_mark_from_a_client_does_nothing(local):
    # Only guarded_app sets scope["tandem_local"]; no header or query string can.
    r = local("GET", "/api/config?tandem_local=1", secret=None, guard=False, headers={"tandem_local": "1", "x-tandem-launch": SECRET})
    assert r.json()["limits"] == {"analyze_seconds": 90, "tune_seconds": 25, "tune_notes": 128}


def test_long_recordings_are_analysed_and_tuned_in_one_request_locally(local):
    long_take = wav(120, rate=8000)
    hosted = local("POST", "/api/analyze?mode=melody", secret=None, guard=False, files={"file": ("a.wav", long_take, "audio/wav")})
    assert hosted.status_code == 400 and "90 seconds" in hosted.text
    r = local("POST", "/api/analyze?mode=melody", files={"file": ("a.wav", long_take, "audio/wav")})
    assert r.status_code == 200 and r.json()["duration"] == 120.0

    take = wav(32)
    # The take is a steady A3 (MIDI 57); only the 129th target asks for B3 (MIDI 59).
    notes = [{"m": 57, "t": round(i * 0.25, 2), "d": 0.2} for i in range(128)] + [{"m": 59, "t": 30.0, "d": 1.5}]
    form = {"notes_json": json.dumps(notes)}
    guards.reset_memory_store()  # the fixture's hosted limit is one audio request per window
    hosted = local("POST", "/api/tune", secret=None, guard=False, files={"file": ("v.wav", take, "audio/wav")}, data=form)
    assert hosted.status_code == 400
    r = local("POST", "/api/tune?strength=1", files={"file": ("v.wav", take, "audio/wav")}, data=form)
    assert r.status_code == 200, r.text
    with wave.open(io.BytesIO(r.content)) as w:
        assert w.getnframes() == 32 * 16000
        tuned = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(float)
    late = tuned[int(30.3 * 16000):int(31.3 * 16000)]
    peak = np.argmax(np.abs(np.fft.rfft(late * np.hanning(len(late))))) * 16000 / len(late)
    assert abs(1200 * np.log2(peak / (440 * 2 ** ((59 - 69) / 12)))) < 25, peak
    too_long = local("POST", "/api/tune", files={"file": ("v.wav", wav(601, rate=8000), "audio/wav")})
    assert too_long.status_code == 400 and "600 seconds" in too_long.text


def test_the_local_body_cap_replaces_the_hosted_one():
    async def inner(scope, receive, send):
        while (await receive()).get("more_body"):
            pass
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})
    mw = guards.RequestGuardMiddleware(inner)
    size = guards.AUDIO_BODY_MAX_BYTES + 1

    async def post(scope_extra, declared):
        sent = []
        chunks = [b"\0" * 1_000_000] * (declared // 1_000_000) + [b"\0" * (declared % 1_000_000)]
        async def receive():
            body = chunks.pop(0)
            return {"type": "http.request", "body": body, "more_body": bool(chunks)}
        async def send(message):
            sent.append(message)
        scope = {"type": "http", "method": "POST", "path": "/api/tune", "client": ("127.0.0.1", 1),
                 "headers": [(b"content-length", str(declared).encode())], **scope_extra}
        await mw(scope, receive, send)
        return sent[0]["status"]

    assert asyncio.run(post({}, size)) == 413
    assert asyncio.run(post({"tandem_local": True}, size)) == 204
    assert asyncio.run(post({"tandem_local": True}, guards.LOCAL_AUDIO_BODY_MAX_BYTES + 1)) == 413
    # Only the exact value True counts as the launcher's mark.
    assert asyncio.run(post({"tandem_local": "1"}, size)) == 413


def test_the_guard_needs_a_real_secret():
    for bad in (None, "", "short", b"x" * 64):
        with pytest.raises(ValueError):
            desk.guarded_app(PORT, bad)


def test_each_launch_gets_a_new_secret():
    assert len({desk.new_launch_secret() for _ in range(20)}) == 20
    assert len(desk.new_launch_secret()) >= 43


def test_the_launch_script_gives_the_secret_to_the_apps_own_origin_only():
    script = desk.launch_script(PORT, SECRET)
    assert f'location.origin==="http://127.0.0.1:{PORT}"' in script
    assert json.dumps(SECRET) in script and '"x-tandem-launch"' in script
    # A quote in the secret could not break out of the string (json.dumps escapes it).
    assert '\\"' in desk.launch_script(PORT, 'a"' + "b" * 40)
