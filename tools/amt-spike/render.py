"""AMT.0 spike: render the spike's Tandem projects to WAV with the studio's own Export WAV.

Starts the app (uvicorn, a free port on 127.0.0.1), opens each project JSON in headless Chromium
through the studio's Open project, and saves Export WAV once every part plays its recorded
samples (the status says "Exported the WAV" with nothing synthesized). Nothing is played aloud.

Run with the repository's own environment (requirements-dev.txt and requirements-e2e.txt):
  .venv/bin/python tools/amt-spike/render.py OUT_DIR project.json [project.json ...]
"""
import os
import pathlib
import socket
import subprocess
import sys
import time

import httpx
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2]
ALL_CONTROLS = """try{localStorage.setItem('tandem-guide',JSON.stringify({view:'all'}))}catch(e){}"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    out = pathlib.Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    projects = [pathlib.Path(p) for p in sys.argv[2:]]
    port = free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TANDEM_", "VERCEL", "UPSTASH_"))}
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "tandem_backend:app", "--host", "127.0.0.1", "--port", str(port)],
                              cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(url + "/api/health").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for project in projects:
                context = browser.new_context(accept_downloads=True)
                context.add_init_script(ALL_CONTROLS)
                page = context.new_page()
                problems = []
                page.on("pageerror", lambda exc: problems.append(str(exc)))
                page.on("console", lambda msg: problems.append(msg.text) if msg.type == "error" else None)
                page.goto(url + "/")
                page.wait_for_function("document.getElementById('notecount').textContent !== ''")
                page.set_input_files("#projectfile", str(project))
                page.wait_for_function("document.getElementById('status').textContent === 'Project opened'")
                page.eval_on_selector("#lanes .lanehead[data-part=\"share\"], #rail .railstep[data-part=\"share\"]", "el => el.click()")
                target = out / (project.stem + ".wav")
                for _ in range(30):
                    with page.expect_download() as info:
                        page.eval_on_selector("#exportwav", "el => el.click()")
                    page.wait_for_function("document.getElementById('status').textContent.startsWith('Export')")
                    status = page.eval_on_selector("#status", "el => el.textContent")
                    if status == "Exported the WAV":
                        info.value.save_as(target)
                        break
                    time.sleep(1)
                else:
                    raise SystemExit(f"{project.name}: samples never loaded ({status})")
                if problems:
                    raise SystemExit(f"{project.name}: browser errors: {problems}")
                print(target, flush=True)
                context.close()
            browser.close()
    finally:
        server.terminate()
        server.wait()


if __name__ == "__main__":
    main()
