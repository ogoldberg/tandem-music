"""ROFORMER.0 spike: Mel-RoFormer and BS-RoFormer vocal separation against HTDemucs.

Every model separates the same clips: SEP.1's fixture mix (tests/separation_fixture.py), its band
alone (nothing sung, so whatever comes out as the vocal is the band left in it) and a 3-minute song
(the mix repeated, for the time and the memory). `score` compares each separated vocal with the
voice the mix was made from. Nothing in Tandem imports this file, and nothing is played aloud.
Commands and environments: tools/roformer-spike/README.md.

  clips      the clips (the repository's .venv: numpy, pyworld)
  weights    each checkpoint's size and hash, whether torch.load(weights_only=True) takes it, and its
             tensors written once to safetensors and read back equal (the spike environment)
  separate   one model over one clip on one device, in a process of its own, with its time and peak
             memory; the RoFormers load from the safetensors files only, HTDemucs through the Mac
             app's own code (the spike environment, with the MSST checkout for the RoFormer classes)
  score      every separated vocal against the voice and the band, to results.json (the .venv:
             melody recall uses the server's transcriber, as SEP.1 does)
  table      results.json as the Markdown tables in docs/AUDIO.md
"""
import argparse
import hashlib
import json
import pathlib
import resource
import sys
import threading
import time
import wave

import numpy as np

REPO = pathlib.Path(__file__).resolve().parents[2]
RATE = 44100
SONG_SECONDS = 180
CLIPS = ("mix", "band", "song")
OFFSET = 0.037   # seconds of silence added in front per run (run k: k * OFFSET)
WARM_UP = 2      # seconds separated once, untimed in the run times, before the timed runs

# The vocal models with a checked license (docs/AUDIO.md, ROFORMER.0). `stem` is what the model's one
# output is; `config` is the YAML that comes with the weights (Kim's is in the MSST checkout).
MODELS = {
    "kim-mel-roformer": {
        "family": "mel", "file": "MelBandRoformer.ckpt",
        "url": "https://huggingface.co/KimberleyJSN/melbandroformer/resolve/ac9b0614ab3cd7f77219e18ba494dfd93956c348/MelBandRoformer.ckpt",
        "sha256": "87201f4d31afb5bc79993230fc49446918425574db48c01c405e44f365c7559e", "bytes": 913106900,
        "config": "msst:configs/KimberleyJensen/config_vocals_mel_band_roformer_kj.yaml",
        "licence": "MIT (relicensed from GPL-3.0 by the author on 2026-04-22, commit ac9b061)",
    },
    "mel-roformer-small": {
        "family": "mel", "file": "mel_band_roformer_small.ckpt",
        "url": "https://huggingface.co/Aname-Tommy/Mel_Band_Roformer_small/resolve/1704b634bee2dd4d912f56c7b5c3cf952961cfb7/mel_band_roformer_small.ckpt",
        "sha256": "20cc592a9dff7dc34a3fb0bf399cd68c950b03ff5f334725e74feb3d0186272f", "bytes": 202573672,
        "config": "w:mel_band_roformer_small.yaml",
        "licence": "MIT (model card tag only)",
    },
    "anvuew-bs-roformer": {
        "family": "bs", "file": "bs_roformer_ft1_anvuew_sdr_12.55.ckpt",
        "url": "https://huggingface.co/anvuew/BS-RoFormer/resolve/24988f47270cb3529b62c4f3bbb8234f4586de9b/bs_roformer_ft1_anvuew_sdr_12.55.ckpt",
        "sha256": "60347271e8493fdff28ef558c3b2297afb869a1f4462594ed548038264bec395", "bytes": 204493312,
        "config": "w:bs_roformer_anvuew.yaml",
        "licence": "GPL-3.0",
    },
}
ALL = ("htdemucs",) + tuple(MODELS)


# ---------------------------------------------------------------- WAV

def write_wav(path, x, rate=RATE):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(np.round(np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def read_wav(path):
    with wave.open(str(path)) as w:
        rate, n = w.getframerate(), w.getnframes()
        data = np.frombuffer(w.readframes(n), "<i2").astype(np.float64) / 32767
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels()).mean(axis=1)
    return data, rate


# ---------------------------------------------------------------- the clips

def cmd_clips(args):
    sys.path.insert(0, str(REPO / "tests"))
    import separation_fixture as fx
    out = pathlib.Path(args.out) / "clips"
    out.mkdir(parents=True, exist_ok=True)
    mix, voice, band = fx.song()
    write_wav(out / "mix.wav", mix)
    write_wav(out / "voice.wav", voice)
    write_wav(out / "band.wav", band)
    write_wav(out / "song.wav", np.tile(mix, int(np.ceil(SONG_SECONDS * RATE / len(mix))))[:SONG_SECONDS * RATE])
    print(f"clips in {out}: mix, voice and band {len(mix) / RATE:.1f} s, song {SONG_SECONDS} s")


# ---------------------------------------------------------------- the weights

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def state_dict_of(loaded):
    """The tensors of a loaded checkpoint: a plain state dict, or one under 'state_dict'/'model'."""
    if isinstance(loaded, dict) and all(hasattr(v, "shape") for v in loaded.values()):
        return loaded, "a plain state dict"
    for key in ("state_dict", "model", "state"):
        if isinstance(loaded, dict) and isinstance(loaded.get(key), dict):
            return loaded[key], f"a state dict under '{key}'"
    raise ValueError(f"no state dict in the checkpoint (top level: {type(loaded).__name__})")


def cmd_weights(args):
    """Each checkpoint: its size and hash against the pin, whether torch.load(weights_only=True) (the
    restricted unpickler, no arbitrary code) takes it, then its tensors written to safetensors and read
    back with safetensors alone, compared tensor for tensor."""
    import torch
    from safetensors.torch import load_file, save_file
    w = pathlib.Path(args.weights)
    report = {}
    for name, spec in MODELS.items():
        p = w / spec["file"]
        entry = {"bytes": p.stat().st_size, "sha256": sha256(p)}
        entry["pin_matches"] = entry["bytes"] == spec["bytes"] and entry["sha256"] == spec["sha256"]
        try:
            loaded = torch.load(p, map_location="cpu", weights_only=True)
            entry["weights_only"] = "loads"
        except Exception as e:  # noqa: BLE001 - the refusal is the finding
            entry["weights_only"] = "refused: " + str(e).split("\n")[0][:200]
            report[name] = entry
            continue
        state, shape = state_dict_of(loaded)
        entry["layout"] = shape
        # Tied tensors (the rotary frequencies every layer shares) are written as copies of their own.
        state = {k.removeprefix("_orig_mod."): v.detach().clone().contiguous() for k, v in state.items()}
        dtypes = sorted({str(v.dtype) for v in state.values()})
        out = w / (p.stem + ".safetensors")
        save_file(state, str(out))
        back = load_file(str(out))
        entry.update({
            "tensors": len(state), "parameters": int(sum(v.numel() for v in state.values())), "dtypes": dtypes,
            "safetensors": out.name, "safetensors_bytes": out.stat().st_size, "safetensors_sha256": sha256(out),
            "read_back_equal": back.keys() == state.keys() and all(torch.equal(back[k], state[k]) for k in state),
        })
        report[name] = entry
    text = json.dumps(report, indent=1)
    (pathlib.Path(args.out) / "weights.json").write_text(text)
    print(text)


# ---------------------------------------------------------------- separation

def load_config(spec, weights, msst):
    import yaml
    where, rel = spec["config"].split(":", 1)
    path = (pathlib.Path(msst) if where == "msst" else pathlib.Path(weights)) / rel
    return yaml.load(path.read_text(), Loader=yaml.FullLoader)  # FullLoader builds the configs' !!python/tuple


def load_roformer(name, weights, msst, device):
    """The model from its safetensors file only (written by `weights`; no pickle at load time), built
    with the MSST checkout's own class and the configuration that comes with the weights."""
    import torch
    from safetensors.torch import load_file
    sys.path.insert(0, str(msst))
    spec = MODELS[name]
    cfg = load_config(spec, weights, msst)
    if spec["family"] == "mel":
        from models.bs_roformer.mel_band_roformer import MelBandRoformer as Model
    else:
        from models.bs_roformer.bs_roformer import BSRoformer as Model
    kwargs = dict(cfg["model"])
    kwargs["use_torch_checkpoint"] = False  # inference only
    model = Model(**kwargs)
    state = load_file(str(pathlib.Path(weights) / (pathlib.Path(spec["file"]).stem + ".safetensors")))
    missing, unexpected = model.load_state_dict(state, strict=False)
    if missing or unexpected:
        raise SystemExit(f"{name}: {len(missing)} missing and {len(unexpected)} unexpected tensors")
    model.eval().to(device)
    return model, cfg


def demix(model, cfg, mix, device, sync):
    """MSST's generic overlap-add (utils/model_utils.py demix, at the pinned commit): chunks of the
    config's chunk_size every chunk_size / num_overlap samples, a linear fade over a tenth of each
    chunk except at the track's ends, reflect padding of chunk_size - step at both ends, in float32."""
    import torch
    import torch.nn.functional as F
    chunk = int(cfg.get("inference", {}).get("chunk_size") or cfg["audio"]["chunk_size"])
    overlap = int(cfg["inference"]["num_overlap"])
    batch = int(cfg["inference"]["batch_size"])
    fade, step = chunk // 10, chunk // overlap
    border = chunk - step
    x = torch.tensor(mix, dtype=torch.float32)
    n0 = x.shape[-1]
    padded = n0 > 2 * border and border > 0
    if padded:
        x = F.pad(x, (border, border), mode="reflect")
    window = torch.ones(chunk)
    window[:fade] = torch.linspace(0, 1, fade)
    window[-fade:] = torch.linspace(1, 0, fade)
    result = torch.zeros(x.shape, dtype=torch.float32)
    counter = torch.zeros(x.shape[-1], dtype=torch.float32)
    parts, places, i = [], [], 0
    with torch.no_grad():
        while i < x.shape[1]:
            part = x[:, i:i + chunk]
            n = part.shape[-1]
            part = F.pad(part, (0, chunk - n), mode="reflect" if n > chunk // 2 else "constant")
            parts.append(part)
            places.append((i, n))
            i += step
            if len(parts) >= batch or i >= x.shape[1]:
                y = model(torch.stack(parts).to(device))
                sync()
                y = y.to("cpu", torch.float32)
                if y.ndim == 4:  # (batch, stems, channels, time): one stem
                    y = y[:, 0]
                for j, (start, n) in enumerate(places):
                    win = window.clone()
                    if start == 0:
                        win[:fade] = 1
                    if start + step >= x.shape[1]:
                        win[-fade:] = 1
                    result[..., start:start + n] += y[j, ..., :n] * win[:n]
                    counter[start:start + n] += win[:n]
                parts.clear(); places.clear()
    out = (result / counter).numpy()
    if padded:
        out = out[..., border:-border]
    return np.nan_to_num(out)


class PeakMemory:
    """The process's peak resident memory (getrusage) and, on Metal, the driver's allocated memory
    sampled every 50 ms."""
    def __init__(self, device):
        self.device, self.mps_peak, self._stop = device, 0, threading.Event()

    def __enter__(self):
        if self.device == "mps":
            import torch

            def sample():
                while not self._stop.wait(0.05):
                    self.mps_peak = max(self.mps_peak, torch.mps.driver_allocated_memory())
            self._thread = threading.Thread(target=sample, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self.device == "mps":
            import torch
            self._thread.join()
            self.mps_peak = max(self.mps_peak, torch.mps.driver_allocated_memory())

    def report(self):
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # bytes on macOS
        if sys.platform != "darwin":
            rss *= 1024
        return {"peak_rss_mb": round(rss / 2**20), "peak_mps_mb": round(self.mps_peak / 2**20) if self.device == "mps" else None}


def cmd_separate(args):
    import torch
    device = args.device
    sync = (torch.mps.synchronize if device == "mps" else (lambda: None))
    clips = pathlib.Path(args.out) / "clips"
    x, rate = read_wav(clips / f"{args.clip}.wav")
    assert rate == RATE
    started_load = time.monotonic()
    with PeakMemory(device) as mem:
        if args.model == "htdemucs":
            sys.path.insert(0, str(REPO))
            from tandem_desktop import models, separation
            rt = models.ModelRuntime(pathlib.Path(args.model_home))
            if not rt.store.installed(models.HTDEMUCS):
                job = rt.jobs.wait(rt.start_download(models.HTDEMUCS.id).id, timeout=1800)
                if job.state != "done":
                    sys.exit(f"download failed: {job.error}")
            rt.store.verify(models.HTDEMUCS)  # hashed again before loading, as the app does
            bag = separation.load_htdemucs(rt.store.folder(models.HTDEMUCS) / separation.WEIGHTS)

            def run(y):  # the Mac app's own call, random shift (shifts=1) included
                return separation.separate(bag, y.astype(np.float32), rate, on=device)[0]
        else:
            model, cfg = load_roformer(args.model, args.weights, args.msst, device)

            def run(y):  # mono in as both channels (the models are stereo), the two outputs averaged
                return demix(model, cfg, np.stack([y, y]), device, sync).mean(axis=0)
        sync()
        load_s = time.monotonic() - started_load
        started = time.monotonic()
        run(x[:WARM_UP * rate])  # the first pass on Metal compiles its kernels: timed on its own
        warm_s = time.monotonic() - started
        vocals, times = [], []
        for k in range(args.runs):
            # Run k: the clip behind k * OFFSET s of silence, which is cut off again afterwards. HTDemucs
            # shifts its input at random on every run anyway; this gives every model the same variants.
            pad = int(round(k * OFFSET * rate))
            started = time.monotonic()
            y = run(np.concatenate([np.zeros(pad), x]))
            sync()
            times.append(round(time.monotonic() - started, 2))
            vocals.append(y[pad:pad + len(x)])
    out = pathlib.Path(args.out) / "vocals" / args.model
    out.mkdir(parents=True, exist_ok=True)
    for k, v in enumerate(vocals):
        write_wav(out / f"{args.clip}-{device}-{k}.wav", v)
    record = {"model": args.model, "clip": args.clip, "device": device, "audio_s": round(len(x) / rate, 2),
              "load_s": round(load_s, 2), "warm_up_s": round(warm_s, 2), "separate_s": times[0], "runs_s": times,
              **mem.report(), "torch": torch.__version__}
    (out / f"{args.clip}-{device}.json").write_text(json.dumps(record, indent=1))
    print(json.dumps(record))


# ---------------------------------------------------------------- scoring

def ratio_db(num, den):
    return 10 * np.log10(max(float(num), 1e-20) / max(float(den), 1e-20))


def rms(x):
    return float(np.sqrt(np.mean(np.square(x))))


def measures(vocal, voice, band, mix):
    """The separated vocal against the voice it should be: SDR (the voice's energy over the error's),
    the error's level relative to the voice, the share of the band the vocal still carries (the vocal
    projected on the band alone, least squares jointly with the voice), and the correlations."""
    n = min(len(vocal), len(voice))
    vocal, voice, band, mix = vocal[:n], voice[:n], band[:n], mix[:n]
    err = vocal - voice
    a = np.stack([voice, band], axis=1)
    (gv, gb), *_ = np.linalg.lstsq(a, vocal, rcond=None)
    return {
        "sdr_db": round(ratio_db(np.sum(voice ** 2), np.sum(err ** 2)), 2),
        "residual_db": round(ratio_db(np.sum(err ** 2), np.sum(voice ** 2)), 2),
        "band_gain": round(float(gb), 4),
        "band_in_vocal_db": round(ratio_db(np.sum((gb * band) ** 2), np.sum((gv * voice) ** 2)), 2),
        "corr_voice": round(float(np.corrcoef(vocal, voice)[0, 1]), 4),
        "corr_band": round(float(np.corrcoef(vocal, band)[0, 1]), 4),
        "level_vs_mix_db": round(20 * np.log10(max(rms(vocal), 1e-10) / rms(mix)), 2),
    }


def summary(each):
    """Mean, lowest and highest of each measure over the runs."""
    out = {}
    for key in each[0]:
        vals = np.array([e[key] for e in each], dtype=float)
        out[key] = round(float(vals.mean()), 4)
        out[key + "_range"] = [round(float(vals.min()), 4), round(float(vals.max()), 4)]
    return out


def cmd_score(args):
    sys.path.insert(0, str(REPO / "tests")); sys.path.insert(0, str(REPO))
    import separation_fixture as fx
    import tandem_backend as server
    out = pathlib.Path(args.out)
    clips = out / "clips"
    mix, _ = read_wav(clips / "mix.wav")
    voice, _ = read_wav(clips / "voice.wav")
    band, _ = read_wav(clips / "band.wav")

    def recall(x):
        return round(fx.recall(server.analyze_melody(x.astype(np.float32), RATE)), 4)

    results = {"reference": {"recall_mix": recall(mix), "recall_voice": recall(voice)}, "models": {}}
    for name in ALL:
        folder = out / "vocals" / name
        if not folder.exists():
            continue
        entry = {}
        for device in ("mps", "cpu"):
            got = {}
            runs = sorted(folder.glob(f"mix-{device}-*.wav"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
            if runs:
                each = []
                for p in runs:
                    v, _ = read_wav(p)
                    each.append({"recall": recall(v), **measures(v, voice, band, mix)})
                got["mix"] = {"runs": each, **summary(each), **json.loads((folder / f"mix-{device}.json").read_text())}
            runs = sorted(folder.glob(f"band-{device}-*.wav"))
            if runs:
                # Nothing is sung: all of this vocal is the band left in it (its level against the band's).
                each = [round(20 * np.log10(max(rms(read_wav(p)[0]), 1e-10) / rms(band)), 2) for p in runs]
                got["band"] = {"vocal_vs_band_db": round(float(np.mean(each)), 2), "runs": each,
                               **json.loads((folder / f"band-{device}.json").read_text())}
            if (folder / f"song-{device}.json").exists():
                got["song"] = json.loads((folder / f"song-{device}.json").read_text())
            if got:
                entry[device] = got
        results["models"][name] = entry
    (out / "results.json").write_text(json.dumps(results, indent=1))
    print(json.dumps(results, indent=1))


def cmd_table(args):
    r = json.loads((pathlib.Path(args.out) / "results.json").read_text())
    ref = r["reference"]
    print(f"Recall of the mixture: {ref['recall_mix']:.2f}; of the voice alone: {ref['recall_voice']:.2f}.\n")
    def spread(d, key, f="{:.2f}"):
        if key not in d:
            return "-"
        lo, hi = d[key + "_range"]
        return f.format(d[key]) + (f" ({f.format(lo)}-{f.format(hi)})" if lo != hi else "")

    print("| Model | Recall, Metal (runs) | Recall, CPU | SDR dB | Error dB re. voice | Band in the vocal dB | "
          "Band alone in, vocal out dB | Corr. with voice / band |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for name, e in r["models"].items():
        m, c = e.get("mps", {}), e.get("cpu", {})
        mm, cm = m.get("mix", {}), c.get("mix", {})
        print(f"| {name} | {spread(mm, 'recall')} | {spread(cm, 'recall')} | {spread(mm, 'sdr_db', '{:.1f}')} | "
              f"{spread(mm, 'residual_db', '{:.1f}')} | {spread(mm, 'band_in_vocal_db', '{:.1f}')} | "
              f"{m.get('band', {}).get('vocal_vs_band_db', '-')} | {mm.get('corr_voice', '-')} / {mm.get('corr_band', '-')} |")
    print("\n| Model | 3-minute song, Metal | Peak memory, Metal (process / GPU) | CPU | Peak memory, CPU | Load |")
    print("| --- | --- | --- | --- | --- | --- |")
    for name, e in r["models"].items():
        m, c = e.get("mps", {}).get("song", {}), e.get("cpu", {}).get("song", {})
        print(f"| {name} | {m.get('separate_s')} s | {m.get('peak_rss_mb')} / {m.get('peak_mps_mb')} MB | "
              f"{c.get('separate_s')} s | {c.get('peak_rss_mb')} MB | {m.get('load_s')} s |")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("clips", "weights", "separate", "score", "table"):
        s = sub.add_parser(name)
        s.add_argument("--out", required=True)
        if name == "weights":
            s.add_argument("--weights", required=True)
        if name == "separate":
            s.add_argument("--model", required=True, choices=ALL)
            s.add_argument("--clip", required=True, choices=CLIPS)
            s.add_argument("--device", required=True, choices=("mps", "cpu"))
            s.add_argument("--runs", type=int, default=1)
            s.add_argument("--weights")
            s.add_argument("--msst")
            s.add_argument("--model-home")
    args = p.parse_args(argv)
    {"clips": cmd_clips, "weights": cmd_weights, "separate": cmd_separate,
     "score": cmd_score, "table": cmd_table}[args.cmd](args)


if __name__ == "__main__":
    main()
