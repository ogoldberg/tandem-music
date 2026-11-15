"""MRT.0 spike: does Magenta RealTime 2 play a Tandem project's notes?

Renders the melody and harmony of tests/fixtures/notation-project.json (F major, 96 bpm, 10 s,
looped to the length asked for) as Magenta RealTime 2's piano roll (128 pitches, 25 frames a
second, 2 on a note's first frame and 1 while it is held), with a style in words, into 48 kHz
stereo music with the exported MLX model, one 40 ms frame at a time (the way live control would
drive it). The same notes a tritone up are the control. For each output it measures:

  - the pitch-class match GEN.2 uses (docs/AUDIO.md): the cosine similarity of the output's
    pitch-class profile (the share of frames whose strongest chroma bin is each pitch class)
    with the notes' profile (each frame's sounding pitch classes, equally weighted), against
    its own notes and against the other notes;
  - the frame match: the share of frames with notes whose strongest pitch class is one of the
    pitch classes sounding then, at the lag (0 to 1 s) where it is highest, and at lag 0;
  - the time: loading and warm-up, and each step (real time is 40 ms a step).

This runs outside Tandem, in its own virtual environment (see the README beside it); nothing in
the app imports it.
"""
import argparse
import hashlib
import json
import os
import pathlib
import time

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "notation-project.json"
FRAME_RATE = 25
RATE = 48000
PERIOD = 10.0  # the fixture is four bars at 96 bpm


def fixture_notes():
    project = json.loads(FIXTURE.read_text())["project"]
    return project["notes"] + project["harmony"]


def piano_roll(notes, seconds, shift=0):
    """(frames, 128) ints: 0 off, 1 held, 2 the note's first frame; the notes repeat every PERIOD."""
    frames = int(round(seconds * FRAME_RATE))
    roll = np.zeros((frames, 128), dtype=np.int32)
    loops = int(np.ceil(seconds / PERIOD))
    for k in range(loops):
        for n in notes:
            m = n["m"] + shift
            start = int(round((n["t"] + k * PERIOD) * FRAME_RATE))
            end = max(start + 1, int(round((n["t"] + n["d"] + k * PERIOD) * FRAME_RATE)))
            if start >= frames:
                continue
            held = roll[start + 1:end, m]
            roll[start + 1:end, m] = np.maximum(held, 1)
            roll[start, m] = 2
    return roll


def notes_profile(roll):
    active = (roll > 0)
    pcs = np.zeros((len(roll), 12))
    for m in range(128):
        pcs[:, m % 12] += active[:, m]
    pcs = (pcs > 0).astype(float)
    sounding = pcs.sum(1) > 0
    weights = pcs[sounding] / pcs[sounding].sum(1, keepdims=True)
    return weights.mean(0), pcs


def audio_chroma(y):
    """One strongest pitch class per 40 ms frame (C = 0), and which frames are not silent."""
    mono = (y.mean(1) if y.ndim == 2 else y).astype(np.float64)
    hop, n_fft = RATE // FRAME_RATE, 8192
    frames = len(mono) // hop
    padded = np.pad(mono, (n_fft // 2, n_fft // 2 + hop))
    window = np.hanning(n_fft)
    freqs = np.fft.rfftfreq(n_fft, 1 / RATE)
    band = (freqs >= 55) & (freqs <= 4200)  # A1 to about C8
    pc = (np.round(12 * np.log2(freqs[band] / 440)).astype(int) + 69) % 12
    fold = np.zeros((band.sum(), 12))
    fold[np.arange(band.sum()), pc] = 1
    strongest, rms = np.zeros(frames, dtype=int), np.zeros(frames)
    for i in range(frames):
        seg = padded[i * hop:i * hop + n_fft]
        power = np.abs(np.fft.rfft(seg * window)) ** 2
        strongest[i] = int((power[band] @ fold).argmax())
        rms[i] = np.sqrt(np.mean(seg ** 2))
    loud = rms > max(1e-4, 0.05 * float(np.median(rms)))
    return strongest, loud


def cosine(a, b):
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def scores(y, rolls):
    """GEN.2's profile match and the frame match of output `y` against each roll in `rolls`."""
    strongest, loud = audio_chroma(y)
    onehot = np.zeros((len(strongest), 12))
    onehot[np.arange(len(strongest)), strongest] = 1
    out_profile = onehot[loud].mean(0)
    result = []
    for roll in rolls:
        profile, pcs = notes_profile(roll)
        n = min(len(pcs), len(strongest))
        by_lag = []
        for lag in range(0, FRAME_RATE + 1):
            idx = np.arange(lag, n)
            src = idx - lag
            keep = loud[idx] & (pcs[src].sum(1) > 0)
            hit = pcs[src[keep], strongest[idx[keep]]]
            by_lag.append(float(hit.mean()) if keep.any() else 0.0)
        best = int(np.argmax(by_lag))
        result.append({"profile_cosine": round(cosine(out_profile, profile), 3),
                       "frame_match_lag0": round(by_lag[0], 3),
                       "frame_match_best": round(by_lag[best], 3),
                       "best_lag_ms": best * 1000 // FRAME_RATE})
    return result


def generate(mrt, style_tokens, roll, drums, cfg_notes):
    from magenta_rt.config import DRUM_PIANOROLL, MUSICCOCA, PIANOROLL_WITH_ONSETS
    state, chunks, steps = None, [], []
    for frame in roll:
        cond = {MUSICCOCA.key: style_tokens, PIANOROLL_WITH_ONSETS.key: frame.tolist(),
                DRUM_PIANOROLL.key: [1 if drums else 0]}
        t0 = time.perf_counter()
        wav, state = mrt.generate(conditioning=cond, cfg_scales={"notes": cfg_notes}, frames=1, state=state)
        steps.append(time.perf_counter() - t0)
        chunks.append(wav.samples)
    return np.concatenate(chunks, 0), np.array(steps)


def file_manifest(home):
    """Size and SHA-256 of every downloaded model file, as MODEL.1 would pin them."""
    out = {}
    for path in sorted(pathlib.Path(home).rglob("*")):
        if path.is_file() and ".cache" not in path.parts:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for block in iter(lambda: f.read(1 << 22), b""):
                    h.update(block)
            out[str(path.relative_to(home))] = {"size": path.stat().st_size, "sha256": h.hexdigest()}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", default="mrt2_small", choices=["mrt2_small", "mrt2_base"])
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--style", default="pop band with piano, bass and drums")
    ap.add_argument("--cfg-notes", type=float, default=1.0)
    ap.add_argument("--no-drums", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True, help="folder for the WAVs and results.json")
    ap.add_argument("--manifest", action="store_true", help="also hash every model file (slow)")
    args = ap.parse_args()

    import mlx.core as mx
    import soundfile as sf
    from magenta_rt import MagentaRT2StdMlxfn, paths

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    mx.random.seed(args.seed)
    t0 = time.perf_counter()
    mrt = MagentaRT2StdMlxfn(size=args.model)
    load_s = time.perf_counter() - t0
    style_tokens = mrt.tokenize_style(mrt.embed_style(args.style, use_mapper=True)).tolist()[:12]

    notes = fixture_notes()
    rolls = [piano_roll(notes, args.seconds, 0), piano_roll(notes, args.seconds, 6)]
    runs = []
    for shift, roll in zip((0, 6), rolls):
        started = time.perf_counter()
        y, steps = generate(mrt, style_tokens, roll, not args.no_drums, args.cfg_notes)
        total = time.perf_counter() - started
        name = f"{args.model}-cfg{args.cfg_notes:g}-shift{shift}.wav"
        sf.write(out / name, y, RATE)
        own, other = scores(y, [rolls[0 if shift == 0 else 1], rolls[1 if shift == 0 else 0]])
        runs.append({"shift": shift, "wav": name, "seconds": round(len(y) / RATE, 2),
                     "generate_s": round(total, 1), "realtime_factor": round(total / args.seconds, 2),
                     "step_ms_mean": round(1000 * steps.mean(), 1),
                     "step_ms_p95": round(1000 * float(np.percentile(steps, 95)), 1),
                     "own": own, "other": other})
        print(json.dumps(runs[-1]))
    result = {"model": args.model, "style": args.style, "cfg_notes": args.cfg_notes,
              "drums": not args.no_drums, "seed": args.seed, "load_and_warmup_s": round(load_s, 1),
              "magenta_home": str(paths.magenta_home()), "runs": runs}
    if args.manifest:
        result["files"] = file_manifest(paths.magenta_home())
    (out / f"results-{args.model}-cfg{args.cfg_notes:g}.json").write_text(json.dumps(result, indent=2))
    print(f"load+warm-up {load_s:.1f} s; results in {out}")


if __name__ == "__main__":
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    main()
