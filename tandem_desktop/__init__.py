"""DESK.1: the Mac app's launcher, without the window.

`python -m tandem_desktop` (see __main__.py) runs the same FastAPI app as the hosted site on a
loopback-only port and opens it in a native WKWebView window. Everything here is free of
pywebview so it can be tested on any platform.

The port is chosen on the first launch and kept: the page's draft, versions and recordings live
in the web view's storage for the origin http://127.0.0.1:<port>, so a different port would be a
different origin and would hide them.

DESK.2: every launch makes a new secret. The launcher puts it in its own window's page (see
__main__.py), the page sends it in the x-tandem-launch header on every /api/ request, and the
server refuses /api/ requests without it and any request from another origin. Requests that pass
are marked local (scope["tandem_local"]), and only those get the lifted limits: no rate limits and
long recordings tuned and analysed in one request. The secret keeps out web pages in the user's
browser; other programs running as the same user can read it and are outside this threat model.
"""
import hmac
import json
import os
import secrets
import socket
import threading
import time
from pathlib import Path

DEFAULT_PORT = 47823
DEFAULT_HOME = Path.home() / "Library" / "Application Support" / "Tandem"
SETTINGS = "desktop.json"

# WKMediaCaptureType values (WebKit/WKUIDelegate.h).
MEDIA_CAMERA = 0
MEDIA_MICROPHONE = 1
MEDIA_CAMERA_AND_MICROPHONE = 2


class DesktopError(Exception):
    """A launch problem the person can act on; the message says what to do."""


def _someone_listens(port):
    """Whether a program accepts connections on 127.0.0.1:<port>, including one listening on all
    interfaces (0.0.0.0), which macOS lets a SO_REUSEADDR socket bind beside (issue #48)."""
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _port_is_free(port):
    if _someone_listens(port):
        return False
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _any_free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def desktop_home():
    """The Mac app's settings folder: TANDEM_DESKTOP_HOME, else ~/Library/Application Support/Tandem."""
    return Path(os.environ.get("TANDEM_DESKTOP_HOME") or DEFAULT_HOME)


def load_port(home=None):
    """The app's port: read from <home>/desktop.json, or chosen and saved on the first launch.

    <home> defaults to desktop_home()."""
    if home is None:
        home = desktop_home()
    home = Path(home)
    path = home / SETTINGS
    if path.exists():
        try:
            port = json.loads(path.read_text())["port"]
        except (ValueError, KeyError, TypeError) as exc:
            raise DesktopError(f"{path} is damaged ({exc}). Fix or remove it; removing it starts "
                               "Tandem on a new port, where earlier drafts and versions do not show.") from exc
        if type(port) is not int or not 1024 <= port <= 65535:
            raise DesktopError(f"{path} names port {port!r}; the port must be a whole number from 1024 to 65535.")
        return port
    port = DEFAULT_PORT if _port_is_free(DEFAULT_PORT) else _any_free_port()
    home.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"port": port}))
    os.replace(tmp, path)
    return port


def bind(port):
    """A listening socket on 127.0.0.1:<port> only, never on other interfaces."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Lets a relaunch reuse the port while the last run's connections are in TIME_WAIT. On macOS it
    # would also let the bind succeed beside a program listening on 0.0.0.0:<port>, so that case
    # is caught first by trying to connect.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        if _someone_listens(port):
            raise OSError(f"something is listening on port {port}")
        sock.bind(("127.0.0.1", port))
        sock.listen(128)
    except OSError as exc:
        sock.close()
        raise DesktopError(f"Port {port} on 127.0.0.1 is in use. Is Tandem already running? "
                           "Quit the other copy and try again.") from exc
    return sock


LAUNCH_HEADER = "x-tandem-launch"


def new_launch_secret():
    """A fresh secret for one launch: 256 random bits, URL-safe so it fits in a header."""
    return secrets.token_urlsafe(32)


def _is_api(path):
    # Starlette matches routes exactly and case-sensitively, so every API route is under /api/.
    return path == "/api" or path.startswith("/api/")


def guarded_app(port, secret, inner=None, desktop_api=None, ai_settings=None, models=None, separation=None):
    """Wrap the ASGI app for the Mac app's local server.

    - Host must be exactly 127.0.0.1:<port> (421 otherwise). A web page in an ordinary browser can
      reach a loopback port; this stops DNS-rebinding pages, whose requests carry their own host.
    - An Origin header, when sent, must be the app's own origin http://127.0.0.1:<port> (403
      otherwise), so no other origin gets CORS approval or reaches a route, even with a simple
      request that needs no preflight.
    - /api/ requests must carry the launch secret in the x-tandem-launch header, compared in
      constant time (403 otherwise). It is read from that header only, never from a query
      string or a cookie.
    Requests that pass are marked scope["tandem_local"] = True, which lifts the hosted limits.
    /api/desktop/ requests that pass go to `desktop_api` (DESK.3's project folders, projects.py)
    and never reach the hosted app; without it they are answered 404. /api/desktop/ai requests go
    to `ai_settings` (AI.4, ai_keys.py), which the hosted app also receives as scope["tandem_ai"]
    so /api/chat uses the person's own provider, model and Keychain key. /api/desktop/models and
    /api/desktop/jobs requests go to `models` (MODEL.1, models.py), which the hosted app also
    receives as scope["tandem_models"] so /api/config says which models are installed.
    /api/desktop/separate requests go to `separation` (SEP.1, separation.py).
    """
    if not isinstance(secret, str) or len(secret) < 32:
        raise ValueError("guarded_app needs the launch secret from new_launch_secret()")
    if inner is None:
        from tandem_backend import app as inner
    expected_host = f"127.0.0.1:{port}".encode()
    own_origin = f"http://127.0.0.1:{port}".encode()
    secret_bytes = secret.encode()
    header = LAUNCH_HEADER.encode()

    async def refuse(scope, send, status, text):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
        await send({"type": "http.response.body", "body": text})

    async def app(scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await inner(scope, receive, send)
            return
        headers = scope.get("headers", [])
        if [v for k, v in headers if k == b"host"] != [expected_host]:
            await refuse(scope, send, 421, b"Unknown host")
            return
        origins = [v for k, v in headers if k == b"origin"]
        if origins and origins != [own_origin]:
            await refuse(scope, send, 403, b"Requests from other origins are refused")
            return
        if _is_api(scope.get("path", "")):
            given = [v for k, v in headers if k == header]
            if len(given) != 1 or not hmac.compare_digest(given[0], secret_bytes):
                await refuse(scope, send, 403, b"This server answers only the Tandem app's own window")
                return
        path = scope.get("path", "")
        if path == "/api/desktop/ai" or path.startswith("/api/desktop/ai/"):
            if ai_settings is None:
                await refuse(scope, send, 404, b"Not found")
                return
            await ai_settings({**scope, "tandem_local": True}, receive, send)
            return
        if path in ("/api/desktop/models", "/api/desktop/jobs") or path.startswith(("/api/desktop/models/", "/api/desktop/jobs/")):
            if models is None:
                await refuse(scope, send, 404, b"Not found")
                return
            await models({**scope, "tandem_local": True}, receive, send)
            return
        if path == "/api/desktop/separate" or path.startswith("/api/desktop/separate/"):
            if separation is None:
                await refuse(scope, send, 404, b"Not found")
                return
            await separation({**scope, "tandem_local": True}, receive, send)
            return
        if path.startswith("/api/desktop/"):
            if desktop_api is None:
                await refuse(scope, send, 404, b"Not found")
                return
            await desktop_api({**scope, "tandem_local": True}, receive, send)
            return
        local = {**scope, "tandem_local": True}
        if ai_settings is not None:
            local["tandem_ai"] = ai_settings
        if models is not None:
            local["tandem_models"] = models
        await inner(local, receive, send)

    return app


def launch_script(port, secret):
    """JavaScript the launcher adds to its window at document start: it gives the page the launch
    secret, but only when the page is the app's own origin, so a page the window might navigate
    to elsewhere never sees it."""
    origin = f"http://127.0.0.1:{port}"
    return ("if(location.origin===" + json.dumps(origin) + ")Object.defineProperty(window,'tandemLaunch',"
            "{value:Object.freeze({header:" + json.dumps(LAUNCH_HEADER) + ",secret:" + json.dumps(secret) + "})});")


def allow_media(scheme, host, port, kind, own_port):
    """Whether the web view may give a page the capture it asks for: only the microphone, only to
    the app's own page."""
    return kind == MEDIA_MICROPHONE and scheme == "http" and host == "127.0.0.1" and port == own_port


def start_server(port, secret, desktop_api=None, ai_settings=None, models=None, separation=None, timeout=30):
    """Start the studio on 127.0.0.1:<port> in a background thread; returns (server, thread)."""
    import uvicorn
    app = guarded_app(port, secret, desktop_api=desktop_api, ai_settings=ai_settings, models=models,
                      separation=separation)
    sock = bind(port)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    server._tandem_previous_runtime = os.environ.get("TANDEM_RUNTIME")
    os.environ["TANDEM_RUNTIME"] = "desktop"
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, name="tandem-server", daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            stop_server(server, thread)
            sock.close()
            raise DesktopError("The Tandem server did not start; see the messages above.")
        time.sleep(0.05)
    server._tandem_socket = sock
    return server, thread


def stop_server(server, thread, timeout=10):
    server.should_exit = True
    thread.join(timeout)
    sock = getattr(server, "_tandem_socket", None)
    if sock is not None:
        sock.close()
    previous = getattr(server, "_tandem_previous_runtime", None)
    if previous is None:
        os.environ.pop("TANDEM_RUNTIME", None)
    else:
        os.environ["TANDEM_RUNTIME"] = previous
