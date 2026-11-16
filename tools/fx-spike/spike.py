"""FX.0: the MPC Plugin SDK's StereoDelay, as WebAssembly in an AudioWorklet against a native build.

    python tools/fx-spike/spike.py run --build <dir> --out <dir>

`--build` is the folder `build.sh` wrote (delay.wasm, fx-native). `run` writes the inputs (SEP.1's
fixture voice, a sung vocal take, and a lone impulse), renders each through the native build, the
same WebAssembly in Node and in an AudioWorklet in headless Chromium (an OfflineAudioContext), at
the example's defaults (1/8 synced at the tempo, ping-pong) and with free time and ping-pong off,
compares the renders sample by sample, checks the echoes of the impulse land where the delay puts
them, times each engine, and writes `results.json` and WAVs of the voice renders to `--out`.
Nothing in Tandem imports this folder, and nothing is played aloud.
"""
import argparse
import base64
import http.server
import json
import pathlib
import subprocess
import sys
import threading
import wave

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
RATE = 44100
# The port's parameter indices (stereo_delay.cpp): sync, division, time ms, feedback %, low cut,
# high cut, ping-pong, mix %.
SYNC, DIVISION, TIME, FEEDBACK, LOWCUT, HIGHCUT, PINGPONG, MIX = range(8)
EIGHTH = 7  # dsp/tempo.h kDivisionEighth: half a beat
SETTINGS = {
    # The example's defaults at the tempo of SEP.1's fixture song (120 bpm): a 250 ms ping-pong.
    "defaults": {"bpm": 120.0, "params": []},
    # Free time, both channels their own delay, more feedback and mix.
    "free": {"bpm": 120.0, "params": [(SYNC, 0), (TIME, 350), (PINGPONG, 0), (FEEDBACK, 60), (MIX, 50)]},
}
IMPULSE_AT = 1.0  # seconds: after the delay time's 80 ms glide up from one sample has settled


def delay_seconds(setting):
    p = dict(SETTINGS[setting]["params"])
    if p.get(SYNC, 1) == 1:
        beats = 0.5 if p.get(DIVISION, EIGHTH) == EIGHTH else None
        return beats * 60.0 / SETTINGS[setting]["bpm"]
    return p[TIME] / 1000.0


def expected_echoes(setting, count=4):
    """Times of the first echoes of an impulse at IMPULSE_AT, per channel.

    Ping-pong: the input goes into the left delay, the left's output feeds the right and the
    right's the left, so the left echoes at d, 3d, 5d and the right at 2d, 4d. Without ping-pong
    each channel feeds itself: both echo at d, 2d, 3d."""
    d = delay_seconds(setting)
    pingpong = dict(SETTINGS[setting]["params"]).get(PINGPONG, 1) == 1
    if pingpong:
        left = [IMPULSE_AT + (2 * k + 1) * d for k in range(count)]
        right = [IMPULSE_AT + (2 * k + 2) * d for k in range(count)]
    else:
        left = right = [IMPULSE_AT + (k + 1) * d for k in range(count)]
    return {"left": left, "right": right}


def echo_peaks(y, rate=RATE, after=IMPULSE_AT, floor=1e-3, gap=0.05):
    """Times of the echoes in `y`: local peaks of |y| above `floor`, at least `gap` s apart,
    after the impulse itself."""
    a = np.abs(np.asarray(y, dtype=np.float64))
    start = int((after + 0.005) * rate)
    peaks, i, g = [], start, int(gap * rate)
    while i < len(a):
        if a[i] >= floor:
            j = i + int(np.argmax(a[i:i + g]))
            peaks.append(j / rate)
            i = j + g
        else:
            i += 1
    return peaks


def compare(a, b):
    """Sample-by-sample comparison of two renders (float32 arrays of the same shape)."""
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    if a.shape != b.shape:
        raise ValueError(f"shapes differ: {a.shape} and {b.shape}")
    diff = a.astype(np.float64) - b.astype(np.float64)
    rms = float(np.sqrt(np.mean(a.astype(np.float64) ** 2)))
    err = float(np.sqrt(np.mean(diff ** 2)))
    return {
        "samples": int(a.size),
        "identical": int(np.count_nonzero(a == b)),
        "bit_exact": bool(np.array_equal(a.view(np.uint32), b.view(np.uint32))),
        "max_abs_diff": float(np.max(np.abs(diff))) if a.size else 0.0,
        "null_db": (20 * np.log10(err / rms)) if err > 0 and rms > 0 else None,
    }


def write_wav(path, left, right):
    s = np.clip(np.stack([left, right], axis=1), -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((s * 32767).astype("<i2").tobytes())


def inputs():
    sys.path.insert(0, str(REPO / "tests"))
    import separation_fixture as fx

    voice = fx.voice(RATE).astype(np.float32)
    impulse = np.zeros(int(3.5 * RATE), dtype=np.float32)
    impulse[int(IMPULSE_AT * RATE)] = 1.0
    return {"voice": voice, "impulse": impulse}


def args_for(setting):
    s = SETTINGS[setting]
    return [str(s["bpm"])] + [f"{p}={v}" for p, v in s["params"]]


def split(raw, n):
    x = np.frombuffer(raw, dtype="<f4")
    return x[:n].copy(), x[n:2 * n].copy()


def run_native(build, out, name, setting, n):
    dest = out / f"{name}-{setting}-native.f32"
    r = subprocess.run([str(build / "fx-native"), str(out / f"{name}.f32"), str(dest), *args_for(setting)],
                       check=True, capture_output=True, text=True)
    return split(dest.read_bytes(), n), json.loads(r.stdout)


def run_node(build, out, name, setting, n):
    dest = out / f"{name}-{setting}-node.f32"
    r = subprocess.run(["node", str(HERE / "wasm_node.mjs"), str(build / "delay.wasm"), str(out / f"{name}.f32"),
                        str(dest), *args_for(setting)], check=True, capture_output=True, text=True)
    return split(dest.read_bytes(), n), json.loads(r.stdout)


PAGE = """<!doctype html><meta charset="utf-8"><title>fx</title><script>
async function render(b64, bpm, params, passthrough, repeat) {
  const raw = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const one = new Float32Array(raw.buffer);
  const mono = new Float32Array(one.length * repeat);
  for (let k = 0; k < repeat; k++) mono.set(one, k * one.length);
  const wasm = await (await fetch("/delay.wasm")).arrayBuffer();
  const ctx = new OfflineAudioContext(2, mono.length, 44100);
  await ctx.audioWorklet.addModule("/worklet.js");
  const buf = ctx.createBuffer(1, mono.length, 44100);
  buf.copyToChannel(mono, 0);
  const src = new AudioBufferSourceNode(ctx, {buffer: buf});
  const node = new AudioWorkletNode(ctx, "fx-delay", {numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [2],
    processorOptions: {wasm, bpm, params, passthrough}});
  src.connect(node).connect(ctx.destination);
  src.start(0);
  const t0 = performance.now();
  const out = await ctx.startRendering();
  const ms = performance.now() - t0;
  if (repeat !== 1) return {ms};
  const both = new Float32Array(mono.length * 2);
  both.set(out.getChannelData(0));
  both.set(out.getChannelData(1), mono.length);
  let s = "";
  const bytes = new Uint8Array(both.buffer);
  for (let i = 0; i < bytes.length; i += 32768) s += String.fromCharCode(...bytes.subarray(i, i + 32768));
  return {ms, b64: btoa(s)};
}
</script>"""


def run_browser(build, signals, settings, timing_seconds=60):
    from playwright.sync_api import sync_playwright

    files = {
        "/": (PAGE.encode(), "text/html"),
        "/worklet.js": ((HERE / "worklet.js").read_bytes(), "text/javascript"),
        "/delay.wasm": ((build / "delay.wasm").read_bytes(), "application/wasm"),
    }
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body, kind = files.get(self.path.split("?")[0], (b"", None))
            self.send_response(200 if kind else 404)
            self.send_header("Content-Type", kind or "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    renders, timing = {}, {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.goto(f"http://127.0.0.1:{port}/")
        version = browser.version
        for name, x in signals.items():
            b64 = base64.b64encode(x.astype("<f4").tobytes()).decode()
            for setting in settings:
                s = SETTINGS[setting]
                r = page.evaluate("([b, bpm, p]) => render(b, bpm, p, false, 1)", [b64, s["bpm"], s["params"]])
                renders[(name, setting)] = split(base64.b64decode(r["b64"]), len(x))
        # Timing: the voice repeated to about a minute, with the module and with a passthrough
        # worklet that does the same copies, best of three each.
        voice = signals["voice"]
        repeat = max(1, round(timing_seconds * RATE / len(voice)))
        b64 = base64.b64encode(voice.astype("<f4").tobytes()).decode()
        for mode in ("wasm", "passthrough"):
            ms = [page.evaluate("([b, pass, n]) => render(b, 120, [], pass, n)", [b64, mode == "passthrough", repeat])["ms"]
                  for _ in range(3)]
            timing[mode] = min(ms)
        browser.close()
    server.shutdown()
    if errors:
        raise RuntimeError(f"page errors: {errors}")
    seconds = repeat * len(voice) / RATE
    return renders, {"chromium": version, "seconds": seconds, "wasm_ms": timing["wasm"],
                     "passthrough_ms": timing["passthrough"],
                     "module_ms_per_second": (timing["wasm"] - timing["passthrough"]) / seconds}


def run(build, out):
    out.mkdir(parents=True, exist_ok=True)
    signals = inputs()
    for name, x in signals.items():
        (out / f"{name}.f32").write_bytes(x.astype("<f4").tobytes())
    settings = list(SETTINGS)
    browser_renders, browser_timing = run_browser(build, signals, settings)
    results = {"settings": {k: {"bpm": v["bpm"], "params": v["params"], "delay_seconds": delay_seconds(k)}
                            for k, v in SETTINGS.items()},
               "renders": {}, "echoes": {}, "timing": {"browser": browser_timing}}
    for name, x in signals.items():
        for setting in settings:
            (nl, nr), native_t = run_native(build, out, name, setting, len(x))
            (wl, wr), node_t = run_node(build, out, name, setting, len(x))
            bl, br = browser_renders[(name, setting)]
            native = np.concatenate([nl, nr])
            key = f"{name}/{setting}"
            results["renders"][key] = {
                "node_vs_native": compare(native, np.concatenate([wl, wr])),
                "worklet_vs_native": compare(native, np.concatenate([bl, br])),
                "wet_vs_dry_db": float(20 * np.log10(np.sqrt(np.mean((np.concatenate([nl, nr]) - np.concatenate([x, x])) ** 2))
                                                     / np.sqrt(np.mean(np.concatenate([x, x]) ** 2)))),
            }
            if name == "voice":
                results["timing"].setdefault("native", {})[setting] = native_t
                results["timing"].setdefault("node", {})[setting] = node_t
                write_wav(out / f"voice-{setting}-native.wav", nl, nr)
                write_wav(out / f"voice-{setting}-worklet.wav", bl, br)
            if name == "impulse":
                exp = expected_echoes(setting)
                results["echoes"][setting] = {
                    "expected": exp,
                    "native": {"left": echo_peaks(nl)[:4], "right": echo_peaks(nr)[:4]},
                    "worklet": {"left": echo_peaks(bl)[:4], "right": echo_peaks(br)[:4]},
                }
    (out / "results.json").write_text(json.dumps(results, indent=2))
    return results


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--build", type=pathlib.Path, required=True)
    r.add_argument("--out", type=pathlib.Path, required=True)
    a = ap.parse_args()
    if a.cmd == "run":
        print(json.dumps(run(a.build.resolve(), a.out.resolve()), indent=2))


if __name__ == "__main__":
    main()
