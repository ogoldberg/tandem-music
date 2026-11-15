"""AMT.0 spike: does the Anticipatory Music Transformer write an accompaniment around a fixed melody?

Stanford's Anticipatory Music Transformer (https://github.com/jthickstun/anticipation) is a GPT-2
over MIDI events (onset time, duration, instrument x pitch, 10 ms steps). Notes given as
"controls" are anticipated: the model sees each one 5 s before it sounds and writes its own
events around it, and the controls never come back in its output, so the melody cannot change.

The input is the melody of tests/fixtures/notation-project.json (F major, 96 bpm, 14 notes over
10 s, played on the flute) looped to the length asked for (30 s by default), shifted 0.1 s later
because the library drops controls in the first 50 ms. The control is the same melody a tritone
up (B major, which shares two of its seven pitch classes with F major). For each output it
measures, over the pitched notes it wrote (drums apart):

  - in key: the share of notes whose pitch class is in the melody's key;
  - consonant: of the notes that start while a melody note sounds, the share whose interval to
    it is a unison, third, fifth or sixth (any octave);
  - shares a triad: of the same notes, the share that make, with the melody note, two notes of
    one triad of the key (I, ii, iii, IV, V, vi in major);
  - each score against its own melody and key ("own") and against the other run's melody and
    key ("other": the notes' output against the tritone melody, and back), so the control shows
    how much of it chance explains;
  - how many notes, which instruments, and how many drum hits;
  - the time per run, on Metal (mps) or the CPU.

harmony.js's own chords and bass for the same melody (tools/amt-spike/harmony.mjs) are scored
the same way.

Subcommands:
  convert   load a model's pytorch_model.bin once with torch.load(weights_only=True), write
            model.safetensors beside it, and check both give the same logits
  run       generate with a model folder that has config.json and model.safetensors (loaded with
            use_safetensors=True, so nothing is unpickled), score it, write MIDI and a Tandem project
  baseline  score harmony.js's accompaniment for the same melody
  table     the results in a folder as a markdown table, means over the seeds

This runs outside Tandem, in its own virtual environment (see the README beside it); nothing in
the app imports it. Nothing is played aloud.
"""
import argparse
import json
import pathlib
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "notation-project.json"
PERIOD = 10.0  # the fixture is four bars at 96 bpm
SHIFT = 0.1  # the library drops controls before 50 ms (sample.generate clips them at DELTA ticks)
RESOLUTION = 100  # the model's 10 ms time steps
MAX_DUR_TICKS = 999  # the model's longest duration is 10 s (1000 steps, 0..999)
FLUTE = 73
DRUMS = 128  # the model's 129th instrument
BAND = (0, 33, DRUMS)  # piano, fingered electric bass, drums: what --band allows
SCALES = {"major": (0, 2, 4, 5, 7, 9, 11), "minor": (0, 2, 3, 5, 7, 8, 10)}
TRIADS = {"major": ((0, "M"), (2, "m"), (4, "m"), (5, "M"), (7, "M"), (9, "m")),
          "minor": ((0, "m"), (3, "M"), (5, "m"), (7, "M"), (8, "M"), (10, "M"))}
CONSONANT = {0, 3, 4, 7, 8, 9}
KICK, SNARE = {35, 36}, {37, 38, 39, 40}  # every other drum key is a hat or cymbal in a Tandem project


def fixture():
    data = json.loads(FIXTURE.read_text())
    return data["project"], data["key"]


def looped(notes, seconds, shift=0):
    """The notes repeated every PERIOD up to seconds, pitches shifted by `shift` semitones."""
    out = []
    k = 0
    while k * PERIOD < seconds:
        for n in notes:
            t = n["t"] + k * PERIOD
            if t < seconds:
                out.append({"m": n["m"] + shift, "t": round(t, 3), "d": round(min(n["d"], seconds - t), 3)})
        k += 1
    return sorted(out, key=lambda n: (n["t"], n["m"]))


def to_events(notes, instrument, offset=SHIFT):
    """Notes as the model's (time, duration, instrument*128+pitch) events in 10 ms steps, offset seconds later."""
    events = []
    for n in notes:
        t = int(round((n["t"] + offset) * RESOLUTION))
        d = max(1, min(MAX_DUR_TICKS, int(round(n["d"] * RESOLUTION))))
        events.append((t, d, instrument * 128 + n["m"]))
    return sorted(events)


def from_events(events, offset=SHIFT):
    """The model's events back as {instrument, m, t, d} in seconds, offset seconds earlier."""
    return [{"instrument": note // 128, "m": note % 128, "t": round(t / RESOLUTION - offset, 3), "d": round(d / RESOLUTION, 3)}
            for t, d, note in events]


def key_pcs(key):
    return {(key["tonic"] + s) % 12 for s in SCALES[key["mode"]]}


def key_triads(key):
    return [frozenset((key["tonic"] + root + i) % 12 for i in ((0, 4, 7) if q == "M" else (0, 3, 7)))
            for root, q in TRIADS[key["mode"]]]


def sounding(melody, t):
    """The melody note sounding at t (the latest to start, if two overlap), or None."""
    best = None
    for n in melody:
        if n["t"] <= t + 1e-9 < n["t"] + n["d"]:
            if best is None or n["t"] > best["t"]:
                best = n
    return best


def scores(notes, melody, key):
    """Key and melody fit of an accompaniment's pitched notes (see the module docstring)."""
    pitched = [n for n in notes if n.get("instrument", 0) != DRUMS]
    scale = key_pcs(key)
    triads = key_triads(key)
    over = [(n, sounding(melody, n["t"])) for n in pitched]
    over = [(n, m) for n, m in over if m is not None]
    consonant = sum(1 for n, m in over if (n["m"] - m["m"]) % 12 in CONSONANT)
    triad = sum(1 for n, m in over if any({n["m"] % 12, m["m"] % 12} <= t for t in triads))
    share = lambda a, b: round(a / b, 3) if b else None  # noqa: E731
    return {
        "notes": len(pitched),
        "in_key": share(sum(1 for n in pitched if n["m"] % 12 in scale), len(pitched)),
        "over_melody": len(over),
        "consonant": share(consonant, len(over)),
        "shares_triad": share(triad, len(over)),
    }


def summary(notes):
    instruments = {}
    for n in notes:
        instruments[n["instrument"]] = instruments.get(n["instrument"], 0) + 1
    return {"instruments": {str(k): v for k, v in sorted(instruments.items())},
            "drum_hits": instruments.get(DRUMS, 0)}


def tandem_project(base, melody, accompaniment):
    """A Tandem project to hear it in the studio: the melody, the pitched notes as the harmony part on piano, the drums."""
    def kind(m):
        return "kick" if m in KICK else "snare" if m in SNARE else "hat"
    harmony = [{"m": n["m"], "t": max(0.0, n["t"]), "d": max(0.01, n["d"])} for n in accompaniment if n["instrument"] != DRUMS]
    drums = [{"k": kind(n["m"]), "t": max(0.0, n["t"])} for n in accompaniment if n["instrument"] == DRUMS]
    return {"format": "tandem-project", "version": 1, "bpm": base["bpm"], "instrument": base["instrument"],
            "melody_locked": True, "notes": melody, "drums": drums, "harmony": harmony, "harmony_instrument": "piano"}


def write_midi(path, melody, accompaniment):
    import mido
    # 0.01 s ticks at 120 bpm (500000 us a beat): 50 ticks a beat
    mid = mido.MidiFile(ticks_per_beat=50)
    channels = {}
    tracks = {}
    all_notes = [dict(n, instrument=FLUTE) for n in melody] + accompaniment
    for n in all_notes:
        instr = n["instrument"]
        if instr not in tracks:
            ch = 9 if instr == DRUMS else len([c for c in channels.values() if c != 9])
            ch = ch + 1 if ch >= 9 and instr != DRUMS else ch
            channels[instr] = ch
            tracks[instr] = []
        tracks[instr].append(n)
    for instr, notes in tracks.items():
        track = mido.MidiTrack()
        mid.tracks.append(track)
        ch = channels[instr]
        if instr != DRUMS:
            track.append(mido.Message("program_change", program=instr, channel=ch, time=0))
        msgs = []
        for n in notes:
            on = int(round(n["t"] * 100))
            off = on + max(1, int(round(n["d"] * 100)))
            msgs.append((on, 1, mido.Message("note_on", note=n["m"], velocity=80, channel=ch)))
            msgs.append((off, 0, mido.Message("note_off", note=n["m"], velocity=0, channel=ch)))
        now = 0
        for at, _, msg in sorted(msgs, key=lambda x: (x[0], x[1])):
            track.append(msg.copy(time=max(0, at - now)))
            now = max(now, at)
    mid.save(path)


def convert(folder):
    import torch
    from safetensors.torch import save_file
    from transformers import AutoModelForCausalLM

    folder = pathlib.Path(folder)
    state = torch.load(folder / "pytorch_model.bin", map_location="cpu", weights_only=True)
    # GPT-2 ties lm_head to the embeddings; safetensors refuses shared tensors, so keep one copy.
    # The export also holds token_out_embeddings = None, which is not a tensor.
    state = {k: v.contiguous().clone() for k, v in state.items() if v is not None and k != "lm_head.weight"}
    out = folder / "safetensors"
    out.mkdir(exist_ok=True)
    (out / "config.json").write_text((folder / "config.json").read_text())
    save_file(state, out / "model.safetensors", metadata={"format": "pt"})
    a = AutoModelForCausalLM.from_pretrained(folder, use_safetensors=False).eval()
    b = AutoModelForCausalLM.from_pretrained(out, use_safetensors=True).eval()
    ids = torch.arange(0, 1023 * 7, 7).remainder(a.config.vocab_size).unsqueeze(0)
    with torch.no_grad():
        diff = (a(ids).logits - b(ids).logits).abs().max().item()
    print(json.dumps({"folder": str(out), "tensors": len(state), "max_logit_difference": diff}))


def band_only(allowed):
    """Patch anticipation.sample so the model writes only these instruments."""
    import anticipation.sample as sample
    from anticipation.config import MAX_INSTR, MAX_PITCH
    from anticipation.vocab import NOTE_OFFSET
    original = sample.instr_logits

    def instr_logits(logits, full_history):
        logits = original(logits, full_history)
        for instr in range(MAX_INSTR):
            if instr not in allowed:
                logits[NOTE_OFFSET + instr * MAX_PITCH:NOTE_OFFSET + (instr + 1) * MAX_PITCH] = -float("inf")
        return logits

    sample.instr_logits = instr_logits


def no_rests():
    """Patch anticipation.sample so the model never samples the rest token.

    The library pads its training sequences with a rest every second where nothing sounds, and
    with only a melody to anticipate the model starts by writing those rests and keeps on (it
    wrote ten rests and two notes in 10 s): without them it has to write notes to move on."""
    import anticipation.sample as sample
    from anticipation.vocab import REST
    original = sample.safe_logits

    def safe_logits(logits, idx):
        logits = original(logits, idx)
        logits[REST] = -float("inf")
        return logits

    sample.safe_logits = safe_logits


def harmony_js(project, style):
    """harmony.js's accompaniment (generateHarmony) for a project, through node."""
    res = subprocess.run(["node", str(pathlib.Path(__file__).with_name("harmony.mjs")), style],
                         input=json.dumps(project), capture_output=True, text=True, check=True)
    return json.loads(res.stdout)["notes"]


def prompt_notes(base, melody, seconds):
    """harmony.js's chords (piano) and bass (fingered bass) for the melody, the ones starting before seconds."""
    project = dict(base, notes=melody)
    notes = [dict(n, instrument=0) for n in harmony_js(project, "chords")]
    notes += [dict(n, instrument=33) for n in harmony_js(project, "bass")]
    return sorted((n for n in notes if n["t"] < seconds - 1e-9), key=lambda n: (n["t"], n["m"]))


def run(args):
    import torch
    from anticipation.sample import generate
    from anticipation.vocab import CONTROL_OFFSET, DUR_OFFSET, NOTE_OFFSET, TIME_OFFSET
    from transformers import AutoModelForCausalLM

    if args.band:
        band_only(set(BAND))
    if args.no_rests:
        no_rests()
    base, key = fixture()
    t0 = time.perf_counter()
    model = AutoModelForCausalLM.from_pretrained(args.model, use_safetensors=True).to(args.device).eval()
    load = time.perf_counter() - t0
    other = {"tonic": (key["tonic"] + 6) % 12, "mode": key["mode"]}
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    name = pathlib.Path(args.model).parent.name if pathlib.Path(args.model).name == "safetensors" else pathlib.Path(args.model).name
    prompt_seconds = args.prompt_bars * 4 * 60 / base["bpm"]
    variant = ("band" if args.band else "free") + ("-norest" if args.no_rests else "") + (f"-prompt{args.prompt_bars}" if args.prompt_bars else "")
    tag = f"{name}-{args.device}-{variant}"
    results = {"model": name, "device": args.device, "band": args.band, "no_rests": args.no_rests,
               "prompt_bars": args.prompt_bars, "seconds": args.seconds, "top_p": args.top_p,
               "load_seconds": round(load, 2), "runs": []}
    for seed in args.seeds:
        for label, shift, own, against in (("notes", 0, key, other), ("tritone", 6, other, key)):
            melody = looped(base["notes"], args.seconds, shift)
            other_melody = looped(base["notes"], args.seconds, 6 - shift)
            controls = []
            for t, d, note in to_events(melody, FLUTE):
                controls += [CONTROL_OFFSET + TIME_OFFSET + t, CONTROL_OFFSET + DUR_OFFSET + d, CONTROL_OFFSET + NOTE_OFFSET + note]
            prompt = prompt_notes(base, melody, prompt_seconds) if args.prompt_bars else []
            inputs = []
            for n in prompt:
                for t, d, note in to_events([n], n["instrument"]):
                    inputs += [TIME_OFFSET + t, DUR_OFFSET + d, NOTE_OFFSET + note]
            if inputs:
                inputs = [tok for ev in sorted(zip(inputs[0::3], inputs[1::3], inputs[2::3])) for tok in ev]
            torch.manual_seed(seed)
            t0 = time.perf_counter()
            tokens = generate(model, prompt_seconds + SHIFT if inputs else 0, args.seconds + SHIFT,
                              inputs=inputs or None, controls=controls, top_p=args.top_p)
            spent = time.perf_counter() - t0
            events = [(t - TIME_OFFSET, d - DUR_OFFSET, n - NOTE_OFFSET) for t, d, n in zip(tokens[0::3], tokens[1::3], tokens[2::3])]
            # Only what the model wrote is scored: the prompt's notes come back in its output.
            notes = [n for n in from_events(events) if n["t"] >= prompt_seconds - 1e-6] if inputs else from_events(events)
            row = {"seed": seed, "input": label, "generate_seconds": round(spent, 2), **summary(notes),
                   "flute_notes": sum(1 for n in notes if n["instrument"] == FLUTE),
                   "own": scores(notes, melody, own), "other": scores(notes, other_melody, against)}
            results["runs"].append(row)
            stem = f"{tag}-{label}-seed{seed}"
            (out / f"{stem}.json").write_text(json.dumps(tandem_project(base, melody, prompt + notes)))
            write_midi(out / f"{stem}.mid", melody, prompt + notes)
            print(json.dumps(row), flush=True)
    (out / f"results-{tag}.json").write_text(json.dumps(results, indent=2))


def baseline(args):
    base, key = fixture()
    other = {"tonic": (key["tonic"] + 6) % 12, "mode": key["mode"]}
    rows = []
    for label, shift, own, against in (("notes", 0, key, other), ("tritone", 6, other, key)):
        melody = looped(base["notes"], args.seconds, shift)
        other_melody = looped(base["notes"], args.seconds, 6 - shift)
        project = dict(base, notes=melody)
        for style in ("chords", "bass"):
            notes = [dict(n, instrument=0) for n in harmony_js(project, style)]
            rows.append({"style": style, "input": label, "notes": len(notes),
                         "own": scores(notes, melody, own), "other": scores(notes, other_melody, against)})
            print(json.dumps(rows[-1]))
    pathlib.Path(args.out).mkdir(parents=True, exist_ok=True)
    (pathlib.Path(args.out) / "results-harmony-js.json").write_text(json.dumps(rows, indent=2))


def table(args):
    """Each results-*.json in a folder as one markdown row a run: means over the seeds."""
    def mean(rows, *path):
        vals = []
        for r in rows:
            v = r
            for k in path:
                v = v[k]
            if v is not None:
                vals.append(v)
        return sum(vals) / len(vals) if vals else None

    def fmt(x, digits=2):
        return "-" if x is None else f"{x:.{digits}f}"

    print("| Model | Device | Variant | Seconds for 30 s, notes / tritone | Notes | Drum hits | Flute notes "
          "| In key, own / other | Consonant, own / other | Shares a triad, own / other |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for path in sorted(pathlib.Path(args.out).glob("results-music-*.json")):
        res = json.loads(path.read_text())
        runs = res["runs"]
        variant = ("band" if res["band"] else "any instrument") + (", no rests" if res.get("no_rests") else "") + \
            (f", {res['prompt_bars']}-bar prompt" if res.get("prompt_bars") else "")
        notes = [r for r in runs if r["input"] == "notes"]
        tritone = [r for r in runs if r["input"] == "tritone"]
        print(f"| {res['model']} | {res['device']} | {variant} "
              f"| {fmt(mean(notes, 'generate_seconds'), 1)} / {fmt(mean(tritone, 'generate_seconds'), 1)} "
              f"| {fmt(mean(runs, 'own', 'notes'), 0)} | {fmt(mean(runs, 'drum_hits'), 0)} | {fmt(mean(runs, 'flute_notes'), 0)} "
              + " ".join(f"| {fmt(mean(runs, 'own', k))} / {fmt(mean(runs, 'other', k))}" for k in ("in_key", "consonant", "shares_triad"))
              + f" |  <!-- {len(runs)} runs, load {res['load_seconds']} s -->")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("convert")
    c.add_argument("--model", required=True)
    r = sub.add_parser("run")
    r.add_argument("--model", required=True, help="a folder with config.json and model.safetensors")
    r.add_argument("--device", default="mps", choices=["mps", "cpu"])
    r.add_argument("--band", action="store_true", help="only piano, bass and drums (else any instrument)")
    r.add_argument("--no-rests", action="store_true", help="never sample the rest token")
    r.add_argument("--prompt-bars", type=int, default=0, help="start from harmony.js's chords and bass for this many bars")
    r.add_argument("--seconds", type=float, default=30.0)
    r.add_argument("--top-p", type=float, default=0.95)
    r.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    r.add_argument("--out", required=True)
    b = sub.add_parser("baseline")
    b.add_argument("--seconds", type=float, default=30.0)
    b.add_argument("--out", required=True)
    t = sub.add_parser("table")
    t.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "table":
        table(args)
    elif args.command == "convert":
        convert(args.model)
    elif args.command == "run":
        run(args)
    else:
        baseline(args)


if __name__ == "__main__":
    main()
