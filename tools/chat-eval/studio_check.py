"""AI.2a: structured AI edits end to end in the studio, with a real model.

chat_eval.py scores a model on the server's chat path alone. This drives the studio itself in Chromium against a
running Tandem server whose /api/chat is set up with a real model (nothing is mocked or canned): it opens the
example song, asks the chat for a few small edits through the chat form, and reads what the studio applied from the
project draft in IndexedDB. Each request is one edit that one Undo takes back; with melody lock on, a request for a
melody change leaves the melody as it was.

    # Local web server (TANDEM_PROVIDER/TANDEM_MODEL/TANDEM_BASE_URL/TANDEM_API_KEY set for the model)
    python tools/chat-eval/studio_check.py --url http://127.0.0.1:8765 --shots shots/ --out check.json

    # The Mac app's server: guarded_app with a launch secret, AI settings saved as in its AI panel ("Another
    # OpenAI-compatible server"), the key from the named environment variable kept in memory (never the Keychain)
    python tools/chat-eval/studio_check.py --desktop --model Inkling-2-Mini-oQ4e-mtp \
      --base-url http://127.0.0.1:8000/v1 --key-env OMLX_API_KEY --shots shots/ --out check.json

--desktop runs the Mac app's own server code (tandem_desktop.start_server: the Host and Origin checks, the launch
secret, the person's saved provider through scope["tandem_ai"]) in a scratch settings folder, and gives the page the
secret with the window's own launch_script. The window itself (WKWebView) is not driven.

Exit code 0 when every check passed, 1 otherwise. The model's replies are kept in --out for reading.
"""
import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ALL_CONTROLS = """try{if(!localStorage.getItem('tandem-guide'))localStorage.setItem('tandem-guide',JSON.stringify({view:'all'}))}catch(e){}"""
DRAFT = """() => new Promise((resolve, reject) => {
  const open = indexedDB.open('tandem');
  open.onerror = () => reject(open.error);
  open.onsuccess = () => {
    const db = open.result, get = db.transaction('kv').objectStore('kv').get('draft');
    get.onsuccess = () => { db.close(); resolve(get.result ?? null); };
    get.onerror = () => reject(get.error);
  };
})"""
# The pages' Content-Security-Policy has no 'unsafe-eval', so Playwright's wait_for_function (a function built from a
# string in the page) is refused; the predicate is written into page.evaluate's own source instead, which runs through
# the DevTools protocol (as e2e/conftest.py does).
def wait_until(page, predicate, arg=None, timeout=30):
    ms = int(timeout * 1000)
    ok = page.evaluate(f"""async (arg) => {{
      const predicate = {predicate}, end = performance.now() + {ms};
      for (;;) {{
        if (predicate(arg)) return true;
        if (performance.now() > end) return false;
        await new Promise(r => requestAnimationFrame(() => r()));
      }}
    }}""", arg)
    if not ok:
        raise TimeoutError(f"timed out after {timeout}s waiting for {predicate}")


# UI.2: the studio's side panel shows one part's settings at a time; as a person would, the part's track lane is
# picked before a control in a hidden panel is used (as e2e/conftest.py does).
REVEAL = """els => { for (const el of els) {
  const panel = el.closest && el.closest('#partpanel [data-panel-part]');
  if (!panel || !panel.hidden) continue;
  const part = panel.dataset.panelPart;
  const pick = document.querySelector('#lanes .lanehead[data-part="' + part + '"]') || document.querySelector('#rail .railstep[data-part="' + part + '"]');
  if (pick) pick.click();
} }"""


def reveal(page, selector):
    page.eval_on_selector_all(selector, REVEAL)
    return selector


PITCHES = lambda p: sorted(n["m"] for n in p["notes"])


def kinds(p):
    out = {}
    for h in p["drums"]:
        out[h["k"]] = out.get(h["k"], 0) + 1
    return out


def is_beat(a, b):
    """A beat was written: kicks, snares and hats, at least four of each, and at least a bar's worth (four) of
    hits the old drums did not have, whether added to them or as a new pattern in their place. The example song
    already has kicks and snares, so one extra or one moved hit is not a beat."""
    k = kinds(b)
    if min(k.get("kick", 0), k.get("snare", 0), k.get("hat", 0)) < 4:
        return False
    old = {(h["k"], round(h["t"], 3)) for h in a["drums"]}
    new = {(h["k"], round(h["t"], 3)) for h in b["drums"]}
    return len(new - old) >= 4


# Each request: what is asked, and a check of (project before, project after) -> (passed, what was seen).
REQUESTS = [
    ("tempo", "Make it a bit faster, about 130 BPM.",
     lambda a, b: (125 <= b["bpm"] <= 135 and PITCHES(a) == PITCHES(b), f"bpm {a['bpm']} -> {b['bpm']}")),
    ("instrument", "Play the melody on flute.",
     lambda a, b: (a["instrument"] != "flute" and b["instrument"] == "flute" and PITCHES(a) == PITCHES(b), f"instrument {a['instrument']} -> {b['instrument']}")),
    ("beat", "Add a simple rock beat.",
     lambda a, b: (is_beat(a, b) and PITCHES(a) == PITCHES(b),
                   f"drums {kinds(a)} -> {kinds(b)}")),
    ("chords", "Add chords to go with the tune.",
     lambda a, b: (len(b.get("harmony") or []) > 0 and PITCHES(a) == PITCHES(b),
                   f"harmony notes {len(a.get('harmony') or [])} -> {len(b.get('harmony') or [])}")),
    ("locked-melody", "Transpose the melody up two semitones.",
     lambda a, b: (PITCHES(a) == PITCHES(b), f"melody {PITCHES(a)} -> {PITCHES(b)}")),
]


class MemoryKeys:
    """A key store in memory, in place of the macOS Keychain, so the check never touches the person's keys."""

    def __init__(self):
        self.keys = {}

    def get(self, account):
        return self.keys.get(account)

    def set(self, account, key):
        self.keys[account] = key

    def delete(self, account):
        self.keys.pop(account, None)


def desktop_server(args, home):
    """The Mac app's server on a free loopback port with AI settings saved as the AI panel saves them."""
    import os
    import socket
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import tandem_desktop as desk
    from tandem_desktop.ai_keys import AISettings
    key = os.environ.get(args.key_env or "")
    if args.key_env and not key:
        sys.exit(f"{args.key_env} is not set")
    ai = AISettings(home, keys=MemoryKeys())
    ai.save({"provider": "custom", "model": args.model, "base_url": args.base_url, **({"key": key} if key else {})})
    if not ai.public()["ready"]:
        sys.exit("The AI settings were saved but are not ready")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    secret = desk.new_launch_secret()
    server, thread = desk.start_server(port, secret, ai_settings=ai)
    return f"http://127.0.0.1:{port}", desk.launch_script(port, secret), lambda: desk.stop_server(server, thread)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", help="a running Tandem web server whose chat is set up")
    ap.add_argument("--desktop", action="store_true", help="run the Mac app's own server here instead of --url")
    ap.add_argument("--model", help="--desktop: the model, as saved in the AI panel")
    ap.add_argument("--base-url", help="--desktop: the OpenAI-compatible server's address")
    ap.add_argument("--key-env", help="--desktop: the environment variable holding the server's key, if it needs one")
    ap.add_argument("--shots", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--timeout", type=float, default=120, help="seconds to wait for each answer")
    args = ap.parse_args()
    if args.desktop == bool(args.url) or (args.desktop and not (args.model and args.base_url)):
        ap.error("give --url, or --desktop with --model and --base-url")
    if not args.desktop:
        return run(args, None)
    import shutil
    import tempfile
    home = tempfile.mkdtemp(prefix="tandem-desktop-check-")
    stop = None
    try:
        args.url, launch, stop = desktop_server(args, home)
        return run(args, launch)
    finally:
        # Always: the Mac app's server stops and the scratch settings folder goes, however the run ended.
        if stop:
            stop()
        shutil.rmtree(home, ignore_errors=True)


def run(args, launch):
    if args.shots:
        args.shots.mkdir(parents=True, exist_ok=True)
    results, problems = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.add_init_script(ALL_CONTROLS)
        if launch:
            context.add_init_script(launch)
        page = context.new_page()
        page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
        page.on("console", lambda m: problems.append(f"console.error: {m.text}") if m.type == "error" else None)
        page.goto(args.url + "/")
        page.wait_for_selector("#demo", state="attached")
        config = page.evaluate("""async () => {
          const l = window.tandemLaunch, headers = l ? {[l.header]: l.secret} : {};
          return (await fetch('/api/config', {headers})).json();
        }""")
        if args.desktop and (config.get("runtime") != "desktop" or config.get("ai_source") == "server"):
            sys.exit(f"Not the Mac app's server with saved AI settings: {config}")
        if not config.get("ai_ready"):
            sys.exit(f"The server's chat is not set up: {config.get('ai_problem') or 'no model'}")
        page.click(reveal(page, "#demo"))
        wait_until(page, "() => document.getElementById('notecount').textContent.startsWith('8 ')")
        if not page.is_checked(reveal(page, "#melodylock")):
            sys.exit("Melody lock should be on for a new song")
        for name, message, check in REQUESTS:
            before = page.evaluate(DRAFT)
            bubbles = page.locator("#chat .bubble").count()
            undo_title = page.get_attribute("#undo", "title")
            page.fill(reveal(page, "#prompt"), message)
            started = time.monotonic()
            page.click(reveal(page, "#chatform button[type=submit]"))
            # The person's bubble, then the reply (and one more for each action the song cannot take).
            wait_until(page, "n => document.querySelectorAll('#chat .bubble').length >= n + 2", bubbles, args.timeout)
            page.wait_for_timeout(300)
            seconds = round(time.monotonic() - started, 1)
            replies = page.locator("#chat .bubble").all_text_contents()[bubbles + 1:]
            status = page.text_content("#status")
            after = page.evaluate(DRAFT)
            passed, seen = check(before, after)
            changed = after != before
            undone = None
            if changed:
                # One request is one edit: one Undo gives back the project as it was before it, then Redo again.
                page.click(reveal(page, "#undo"))
                undone = page.evaluate(DRAFT) == before
                page.click(reveal(page, "#redo"))
                if page.evaluate(DRAFT) != after:
                    problems.append(f"{name}: Redo did not bring the edit back")
            elif page.get_attribute("#undo", "title") != undo_title:
                problems.append(f"{name}: nothing changed but an undo step was added")
            if args.shots:
                page.screenshot(path=str(args.shots / f"{len(results) + 1}-{name}.png"))
            row = {"name": name, "message": message, "replies": replies, "status": status, "seconds": seconds,
                   "passed": bool(passed), "seen": seen, "changed": changed, "one_undo": undone}
            results.append(row)
            print(f"{name}: {'ok' if passed else 'FAILED'} ({seen}); {seconds}s; undo restores: {undone}; "
                  f"status: {status}\n  reply: {' | '.join(replies)[:300]}")
        browser.close()
    ok = all(r["passed"] and r["one_undo"] is not False for r in results) and not problems
    args.out.write_text(json.dumps({"url": args.url, "desktop": args.desktop, "ai_source": config.get("ai_source"), "model": config.get("model"), "provider": config.get("provider"),
                                    "results": results, "problems": problems, "ok": ok}, indent=1) + "\n")
    for p in problems:
        print("problem:", p)
    print("all passed" if ok else "some checks failed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
