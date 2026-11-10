"""DESK.1: the Mac app's launcher (tandem_desktop). These tests need no pywebview: they cover the
fixed port, the loopback-only server, the Host header check and the microphone permission rule."""
import asyncio
import json
import socket

import httpx
import pytest

import tandem_desktop as desk


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
    app = desk.guarded_app(port)
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            return await c.get("/api/health", headers={"host": host.format(port=port)})
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
    app = desk.guarded_app(47999, inner)
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
    server, thread = desk.start_server(port)
    try:
        base = f"http://127.0.0.1:{port}"
        page = httpx.get(base + "/")
        assert page.status_code == 200 and "<title>" in page.text
        config = httpx.get(base + "/api/config").json()
        assert config["runtime"] == "desktop"
        foreign = httpx.get(base + "/api/health", headers={"host": f"attacker.example:{port}"})
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
