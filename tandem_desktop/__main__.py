"""DESK.1: open Tandem in a native window. Run with `python -m tandem_desktop`.

Needs requirements-desktop.txt (pywebview). On macOS the window is a WKWebView; the web view's
storage for the app's origin keeps the draft, versions and recordings between launches.
"""
import sys

import tandem_desktop as desk

MEDIA_SELECTOR = b"webView:requestMediaCapturePermissionForOrigin:initiatedByFrame:type:decisionHandler:"


def install_microphone_rule(port):
    """Answer WebKit's capture requests by allow_media, so the app's own page gets the microphone
    without WebKit asking on every launch, and nothing else gets the microphone or the camera."""
    if sys.platform != "darwin":
        return
    import objc
    import WebKit
    from webview.platforms import cocoa

    def decide(self, web_view, origin, frame, kind, handler):
        ok = desk.allow_media(str(origin.protocol()), str(origin.host()), int(origin.port()), int(kind), port)
        handler(WebKit.WKPermissionDecisionGrant if ok else WebKit.WKPermissionDecisionDeny)

    objc.classAddMethods(cocoa.BrowserView.BrowserDelegate,
                         [objc.selector(decide, selector=MEDIA_SELECTOR, signature=b"v@:@@@q@?")])


def install_launch_secret(window, port, secret):
    """Add desk.launch_script to the window's web view before its first page loads (pywebview's
    before_show event runs on the main thread just before the window loads its URL)."""
    import WebKit
    from webview.platforms import cocoa

    web_view = cocoa.BrowserView.instances[window.uid].webview
    script = WebKit.WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
        desk.launch_script(port, secret), WebKit.WKUserScriptInjectionTimeAtDocumentStart, True)
    web_view.configuration().userContentController().addUserScript_(script)


def main():
    try:
        import webview
    except ImportError:
        print("Tandem's window needs pywebview: python -m pip install -r requirements-desktop.txt", file=sys.stderr)
        return 1
    try:
        port = desk.load_port()
        secret = desk.new_launch_secret()
        server, thread = desk.start_server(port, secret)
    except desk.DesktopError as exc:
        print(f"Tandem could not start: {exc}", file=sys.stderr)
        return 1
    try:
        install_microphone_rule(port)
        webview.settings["ALLOW_DOWNLOADS"] = True
        window = webview.create_window("Tandem", f"http://127.0.0.1:{port}/", width=1280, height=860, min_size=(720, 560))
        if sys.platform == "darwin":
            window.events.before_show += lambda window: install_launch_secret(window, port, secret)
        webview.start(private_mode=False)
    finally:
        desk.stop_server(server, thread)
    return 0


if __name__ == "__main__":
    sys.exit(main())
