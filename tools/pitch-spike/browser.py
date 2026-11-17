"""PITCH.0: the trackers that run in the browser, in headless Chromium against the app's own server.

- basic-pitch-vox3 / basic-pitch-trans2: the vendored Basic Pitch model and contour.js's pitchContour, with
  the contour editor's settings (VOX.3: salience 0.3) and Transcribe's (TRANS.2: salience 0.15, nothing
  below MIDI 36, subharmonics), the code transcription.js runs.
- pesto-web: PESTO's streaming ONNX export (spike.py export) in ONNX Runtime Web (WebAssembly, one thread),
  fed one 10 ms step at a time with its cache, on the page's thread; every step is timed.

Usage (the repository's .venv with requirements-e2e.txt):
  .venv/bin/python tools/pitch-spike/browser.py --out <spike folder> --ort <onnxruntime-web package/dist> --onnx-dir <folder>
Writes tracks/<tracker>/<clip>.json and tracks/browser-steps.json. Nothing is played aloud.
"""
import argparse
import json
import mimetypes
import os
import pathlib
import socket
import subprocess
import sys
import time

import httpx
from playwright.sync_api import sync_playwright

REPO = pathlib.Path(__file__).resolve().parents[2]

BASIC_PITCH = """async ({url, rate}) => {
  const { BasicPitch } = await import("/vendor/basic-pitch-1.0.1-2/basic-pitch.mjs");
  const { pitchContour, MIN_MIDI } = await import("/contour.js");
  const { resampleForBasicPitch, MELODY_SALIENCE, BASIC_PITCH_MODEL } = await import("/transcription.js");
  window.bp ||= new BasicPitch(BASIC_PITCH_MODEL);
  const data = await (await fetch(url)).arrayBuffer();
  const audio = await new OfflineAudioContext(1, 1, rate).decodeAudioData(data);
  const prepared = await resampleForBasicPitch(audio);
  const started = performance.now();
  const contours = [];
  await window.bp.evaluateModel(prepared, (f, o, c) => contours.push(...c), () => {});
  const vox3 = pitchContour(contours, { duration: audio.duration });
  const trans2 = pitchContour(contours, { duration: audio.duration, threshold: MELODY_SALIENCE, lowest: MIN_MIDI, subharmonics: true });
  const seconds = (performance.now() - started) / 1000;
  const list = a => Array.from(a, v => Number.isFinite(v) ? v : null);
  return { seconds, audio_seconds: audio.duration, vox3: { t: Array.from(vox3.t), midi: list(vox3.m) }, trans2: { t: Array.from(trans2.t), midi: list(trans2.m) } };
}"""

PESTO_WEB = """async ({url, rate, model, threshold}) => {
  const ort = await import("/spike/ort/ort.wasm.min.mjs");
  ort.env.wasm.wasmPaths = "/spike/ort/";
  ort.env.wasm.numThreads = 1;
  window.sessions ||= {};
  const loadStarted = performance.now();
  window.sessions[model] ||= await ort.InferenceSession.create(model, { executionProviders: ["wasm"] });
  const load = (performance.now() - loadStarted) / 1000;
  const s = window.sessions[model];
  const data = await (await fetch(url)).arrayBuffer();
  const audio = await new OfflineAudioContext(1, 1, rate).decodeAudioData(data);
  const x = audio.getChannelData(0), chunk = Math.round(rate * 0.01);
  const cacheSize = Number(s.inputMetadata?.[1]?.shape?.[1] ?? 0);
  let cache = new ort.Tensor("float32", new Float32Array(cacheSize), [1, cacheSize]);
  const t = [], midi = [], conf = [], steps = [];
  const started = performance.now();
  for (let i = 0; (i + 1) * chunk <= x.length; i++) {
    const a = performance.now();
    const out = await s.run({ audio: new ort.Tensor("float32", x.slice(i * chunk, (i + 1) * chunk), [1, chunk]), cache });
    steps.push(performance.now() - a);
    cache = out.cache_out;
    const m = out.prediction.data[0], c = out.confidence.data[0];  // fractional MIDI
    t.push((i + 1) * chunk / rate); conf.push(c);
    midi.push(c >= threshold ? m : null);
  }
  return { seconds: (performance.now() - started) / 1000, audio_seconds: audio.duration, load, t, midi, confidence: conf, steps };
}"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--ort", required=True, help="onnxruntime-web's package/dist folder")
    p.add_argument("--onnx-dir", required=True)
    p.add_argument("--threshold", type=float, default=0.5)
    args = p.parse_args()
    root = pathlib.Path(args.out)
    clips = root / "clips"
    ort_dir, onnx_dir = pathlib.Path(args.ort), pathlib.Path(args.onnx_dir)
    port = free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TANDEM_", "VERCEL", "UPSTASH_"))}
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "tandem_backend:app", "--host", "127.0.0.1", "--port", str(port)],
                              cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(150):
            try:
                if httpx.get(url + "/api/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))

            def serve(route):
                path = route.request.url.split("/spike/", 1)[1]
                kind, name = path.split("/", 1)
                base = {"clips": clips, "ort": ort_dir, "onnx": onnx_dir}[kind]
                f = base / name
                route.fulfill(status=200, body=f.read_bytes(), headers={"content-type": mimetypes.guess_type(f.name)[0] or "application/octet-stream"})
            page.route("**/spike/**", serve)
            page.goto(url + "/api/health")
            names = sorted(f.name[:-4] for f in clips.glob("*.wav"))
            rate_of = lambda n: int(n.rsplit("-", 1)[1])
            # Load the model and its kernels once before timing anything.
            page.evaluate(BASIC_PITCH, {"url": f"/spike/clips/{names[0]}.wav", "rate": rate_of(names[0])})
            for name in names:
                r = page.evaluate(BASIC_PITCH, {"url": f"/spike/clips/{name}.wav", "rate": rate_of(name)})
                for key in ("vox3", "trans2"):
                    out = root / "tracks" / f"basic-pitch-{key}"
                    out.mkdir(parents=True, exist_ok=True)
                    (out / f"{name}.json").write_text(json.dumps({"tracker": f"basic-pitch-{key}", "clip": name, **r[key],
                        "seconds": r["seconds"], "audio_seconds": r["audio_seconds"], "load_seconds": None}))
                print(f"basic-pitch {name}: {r['seconds'] / r['audio_seconds'] * 1000:.1f} ms per second of audio")
            steps = {}
            out = root / "tracks" / "pesto-web"
            out.mkdir(parents=True, exist_ok=True)
            for name in names:
                rate = rate_of(name)
                model = f"/spike/onnx/pesto-stream-{rate}-{round(rate * 0.01)}.onnx"
                if not (onnx_dir / model.rsplit("/", 1)[1]).exists():
                    continue
                r = page.evaluate(PESTO_WEB, {"url": f"/spike/clips/{name}.wav", "rate": rate, "model": model, "threshold": args.threshold})
                steps.setdefault(str(rate), []).extend(r.pop("steps"))
                (out / f"{name}.json").write_text(json.dumps({"tracker": "pesto-web", "clip": name, **r, "load_seconds": r.pop("load")}))
                print(f"pesto-web {name}: {r['seconds'] / r['audio_seconds'] * 1000:.1f} ms per second of audio")
            summary = {}
            for rate, st in steps.items():
                st = sorted(st)
                summary[rate] = {"runtime": "onnxruntime-web wasm, 1 thread, Chromium " + browser.version, "steps": len(st),
                                 "mean_ms": sum(st) / len(st), "p50_ms": st[len(st) // 2], "p99_ms": st[int(len(st) * 0.99)], "max_ms": st[-1]}
            (root / "tracks" / "browser-steps.json").write_text(json.dumps(summary, indent=1))
            print(json.dumps(summary, indent=1))
            browser.close()
            if errors:
                sys.exit("page errors: " + "; ".join(errors))
    finally:
        server.terminate()


if __name__ == "__main__":
    main()
