"""DESK.1: the Mac app's launcher, without the window.

`python -m tandem_desktop` (see __main__.py) runs the same FastAPI app as the hosted site on a
loopback-only port and opens it in a native WKWebView window. Everything here is free of
pywebview so it can be tested on any platform.

The port is chosen on the first launch and kept: the page's draft, versions and recordings live
in the web view's storage for the origin http://127.0.0.1:<port>, so a different port would be a
different origin and would hide them.
"""
import json
import os
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


def _port_is_free(port):
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


def load_port(home=None):
    """The app's port: read from <home>/desktop.json, or chosen and saved on the first launch.

    <home> defaults to TANDEM_DESKTOP_HOME, else ~/Library/Application Support/Tandem."""
    if home is None:
        home = os.environ.get("TANDEM_DESKTOP_HOME") or DEFAULT_HOME
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
    # Lets a relaunch reuse the port while the last run's connections are in TIME_WAIT; it does
    # not allow binding while another process is listening on the port.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", port))
        sock.listen(128)
    except OSError as exc:
        sock.close()
        raise DesktopError(f"Port {port} on 127.0.0.1 is in use. Is Tandem already running? "
                           "Quit the other copy and try again.") from exc
    return sock


def guarded_app(port, inner=None):
    """Wrap the ASGI app so it answers only requests whose Host is exactly 127.0.0.1:<port>.

    A web page in an ordinary browser can reach a loopback port; this check stops DNS-rebinding
    pages (whose requests carry their own host name) from reading or driving the local server.
    """
    if inner is None:
        from tandem_backend import app as inner
    expected = f"127.0.0.1:{port}".encode()

    async def app(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            hosts = [v for k, v in scope.get("headers", []) if k == b"host"]
            if hosts != [expected]:
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                    return
                await send({"type": "http.response.start", "status": 421,
                            "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
                await send({"type": "http.response.body", "body": b"Unknown host"})
                return
        await inner(scope, receive, send)

    return app


def allow_media(scheme, host, port, kind, own_port):
    """Whether the web view may give a page the capture it asks for: only the microphone, only to
    the app's own page."""
    return kind == MEDIA_MICROPHONE and scheme == "http" and host == "127.0.0.1" and port == own_port


def start_server(port, timeout=30):
    """Start the studio on 127.0.0.1:<port> in a background thread; returns (server, thread)."""
    import uvicorn
    sock = bind(port)
    server = uvicorn.Server(uvicorn.Config(guarded_app(port), log_level="warning"))
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
