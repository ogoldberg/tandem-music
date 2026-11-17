"""WORDS.0 spike: Whisper for sung lyrics, with a time for each word, against the notes they are sung on.

The first pass runs on the English half of the Children's Song Dataset (CSD 1.1, Zenodo record 4916302,
CC BY-NC-SA 4.0, research use: kept outside the repository and never redistributed): 50 songs, each sung
in two keys by one singer, dry, with the words of each line, the syllables of each line and every
syllable's note (start, end, pitch). Nothing in Tandem imports this file, and nothing is played aloud.
Commands and environments: tools/words-spike/README.md.

  refs     the reference: each recording's words, the note each word starts on, every note onset, and
           the audio as 16 kHz mono WAV (both runtimes read the same files)
  weights  each model's files against their pins (size, SHA-256) and their format
  run      one runtime and one model over every recording, with word times and the time it took
  score    every run against the reference, to results.json
  table    results.json as the Markdown tables in docs/AUDIO.md
"""
import argparse
import csv
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import time
import wave

REPO = pathlib.Path(__file__).resolve().parents[2]

# The models, pinned to one commit each. mlx-whisper reads a folder (config.json + weights); whisper.cpp
# reads one ggml file. All are OpenAI's Whisper weights (MIT), converted by mlx-community or ggerganov.
HF = "https://huggingface.co"
MODELS = {
    ("mlx", "large-v3-turbo"): {
        "repo": "mlx-community/whisper-large-v3-turbo", "commit": "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb",
        "files": {"weights.safetensors": ("951ed3fc1203e6a62467abb2144a96ce7eafca8fa77e3704fdb8635ff3e7f8a6", 1613977612),
                  "config.json": (None, 268)},
        "format": "safetensors"},
    ("mlx", "small.en"): {
        "repo": "mlx-community/whisper-small.en-mlx", "commit": "52a88bf6e98b114a210c21bb83e22d6e1505cb73",
        "files": {"weights.npz": ("1bb29b030aca711a035f7a084a0eefac6251ecc2bdd356fa748858fbad082f5a", 481306200),
                  "config.json": (None, 266)},
        "format": "npz"},
    ("cpp", "large-v3-turbo"): {
        "repo": "ggerganov/whisper.cpp", "commit": "5359861c739e955e79d9a303bcbc70fb988958b1",
        "files": {"ggml-large-v3-turbo.bin": ("1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69", 1624555275)},
        "format": "ggml"},
    ("cpp", "small.en"): {
        "repo": "ggerganov/whisper.cpp", "commit": "5359861c739e955e79d9a303bcbc70fb988958b1",
        "files": {"ggml-small.en.bin": ("c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d", 487614201)},
        "format": "ggml"},
}
WHISPER_CPP_TAG = "v1.9.5"  # commit d1be6fde11ac6e0407606b4e42fe72d34add8037

# --- text --------------------------------------------------------------------------------------------

ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def number_words(n):
    """0..999 as words, as the songs sing them ('one hundred' for 100)."""
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else " " + ONES[n % 10])
    return ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " " + number_words(n % 100))


def normalize(text):
    """Lowercase words without punctuation; digits as words; hyphenated words split; apostrophes kept."""
    text = text.lower().replace("’", "'")
    text = re.sub(r"\d+", lambda m: " " + number_words(int(m.group())) + " " if int(m.group()) < 1000 else m.group(), text)
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    return [w.strip("'") for w in text.split() if w.strip("'")]


# Letters sung on their own are a syllable each, except W (double-u).
LETTER_SYLLABLES = {"w": 3}


def syllable_estimate(word):
    """A rough count of a written English word's syllables: vowel groups, less a silent final e."""
    w = word.lower().strip("'")
    if len(w) == 1:
        return LETTER_SYLLABLES.get(w, 1)
    groups = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and not w.endswith(("le", "ee", "ye")) and groups > 1:
        groups -= 1
    if re.search(r"[^aeiou]ed$", w) and not re.search(r"[td]ed$", w) and groups > 1:
        groups -= 1
    return max(1, groups)


def split_syllables(words, total):
    """How many of a line's `total` syllables each word takes: every word at least one, as near to its
    estimate as can be (least total difference, ties to the earlier words). Returns (counts, exact), exact
    when the estimates already sum to the total."""
    est = [syllable_estimate(w) for w in words]
    n = len(words)
    if n == 0 or total < n:
        return None, False
    if sum(est) == total:
        return est, True
    inf = float("inf")
    cost = [[inf] * (total + 1) for _ in range(n + 1)]
    pick = [[0] * (total + 1) for _ in range(n + 1)]
    cost[0][0] = 0
    for i in range(1, n + 1):
        for used in range(i, total - (n - i) + 1):
            for k in range(1, used - (i - 1) + 1):
                c = cost[i - 1][used - k] + abs(k - est[i - 1])
                if c < cost[i][used]:
                    cost[i][used], pick[i][used] = c, k
    counts, used = [], total
    for i in range(n, 0, -1):
        counts.append(pick[i][used])
        used -= pick[i][used]
    return counts[::-1], False


def song_reference(lyric_lines, syllable_lines, notes):
    """The words of one recording, each with the start of the note its first syllable is sung on.
    `lyric_lines` and `syllable_lines` are lists of tokens per line; `notes` [(start, end, pitch, syllable)]
    in order, one per syllable. When the two files have different line counts the song is one line."""
    if len(lyric_lines) != len(syllable_lines):
        lyric_lines = [[w for line in lyric_lines for w in line]]
        syllable_lines = [[s for line in syllable_lines for s in line]]
    words, at = [], 0
    for lyr, syl in zip(lyric_lines, syllable_lines):
        tokens = [(w, normalize(w)) for w in lyr]
        flat = [x for _, parts in tokens for x in parts]
        counts, exact = split_syllables(flat, len(syl))
        k = at
        for j, w in enumerate(flat):
            start = notes[k][0] if counts and k < len(notes) else None
            words.append({"w": w, "note": start, "exact": exact and counts is not None})
            if counts:
                k += counts[j]
        at += len(syl)
    return words


def read_csd(csd, name):
    """One CSD English recording's lyric lines, syllable lines and notes."""
    base = pathlib.Path(csd) / "english"
    lines = lambda p: [line.split() for line in p.read_text().splitlines() if line.strip()]
    with open(base / "csv" / f"{name}.csv") as f:
        notes = [(float(r["start"]), float(r["end"]), int(r["pitch"]), r["syllable"]) for r in csv.DictReader(f)]
    return lines(base / "lyric" / f"{name}.txt"), lines(base / "txt" / f"{name}.txt"), notes


# --- scoring ------------------------------------------------------------------------------------------

def align(ref, hyp):
    """Word alignment by edit distance (substitution, insertion and deletion each cost one): the WER's
    counts and the pairs of positions (ref index, hyp index) where the words are the same."""
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]), d[i - 1][j] + 1, d[i][j - 1] + 1)
    i, j, pairs, subs, dels, ins = n, m, [], 0, 0, 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            if ref[i - 1] == hyp[j - 1]:
                pairs.append((i - 1, j - 1))
            else:
                subs += 1
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            dels, i = dels + 1, i - 1
        else:
            ins, j = ins + 1, j - 1
    return {"ref": n, "sub": subs, "del": dels, "ins": ins, "pairs": pairs[::-1]}


def nearest(times, t):
    return min(times, key=lambda x: abs(x - t)) if times else None


def percentile(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def score_recording(ref_words, onsets, hyp_words):
    """One recording: the alignment counts, and for every word sung and heard right, its start against
    the note it starts on (when the line's syllables split exactly) and against the nearest note onset."""
    a = align([w["w"] for w in ref_words], [w["w"] for w in hyp_words])
    to_note, to_onset = [], []
    for i, j in a["pairs"]:
        start = hyp_words[j]["start"]
        if ref_words[i]["exact"] and ref_words[i]["note"] is not None:
            to_note.append(start - ref_words[i]["note"])
        to_onset.append(start - nearest(onsets, start))
    return {"ref": a["ref"], "sub": a["sub"], "del": a["del"], "ins": a["ins"], "correct": len(a["pairs"]),
            "to_note": to_note, "to_onset": to_onset}


def summarize(recordings, audio_seconds, run_seconds, failed=0):
    ref = sum(r["ref"] for r in recordings)
    errors = sum(r["sub"] + r["del"] + r["ins"] for r in recordings)
    to_note = [x for r in recordings for x in r["to_note"]]
    to_onset = [x for r in recordings for x in r["to_onset"]]
    absn = [abs(x) for x in to_note]
    # The same after taking away the run's own median offset (fitted on these words): what a fixed correction
    # could reach at best, against the spread no fixed correction removes.
    shift = percentile(to_note, 0.5)
    absd = [abs(x - shift) for x in to_note]
    per = sorted((r["sub"] + r["del"] + r["ins"]) / r["ref"] for r in recordings if r["ref"])
    return {
        "recordings": len(recordings), "failed": failed, "words": ref, "wer": errors / ref if ref else None,
        "sub": sum(r["sub"] for r in recordings), "del": sum(r["del"] for r in recordings),
        "ins": sum(r["ins"] for r in recordings),
        "wer_median_recording": percentile(per, 0.5), "wer_worst_recording": per[-1] if per else None,
        "timed_words": len(to_note),
        "to_note_median": percentile(to_note, 0.5), "to_note_abs_median": percentile(absn, 0.5),
        "to_note_abs_p90": percentile(absn, 0.9),
        "within_100ms": sum(x <= 0.1 for x in absn) / len(absn) if absn else None,
        "within_250ms": sum(x <= 0.25 for x in absn) / len(absn) if absn else None,
        "shifted_abs_median": percentile(absd, 0.5),
        "shifted_within_100ms": sum(x <= 0.1 for x in absd) / len(absd) if absd else None,
        "to_onset_abs_median": percentile([abs(x) for x in to_onset], 0.5),
        "audio_minutes": audio_seconds / 60, "run_seconds": run_seconds,
        "seconds_per_minute": run_seconds / (audio_seconds / 60) if audio_seconds else None,
    }


# --- commands -----------------------------------------------------------------------------------------

def recordings(csd):
    names = sorted(p.stem for p in (pathlib.Path(csd) / "english" / "csv").glob("*.csv"))
    if len(names) != 100:
        sys.exit(f"expected 100 English recordings in {csd}, found {len(names)}")
    return names


def cmd_refs(a):
    out = pathlib.Path(a.out)
    (out / "wav16").mkdir(parents=True, exist_ok=True)
    refs = {}
    for name in recordings(a.csd):
        lyric, syl, notes = read_csd(a.csd, name)
        src = pathlib.Path(a.csd) / "english" / "wav" / f"{name}.wav"
        dst = out / "wav16" / f"{name}.wav"
        if not dst.exists():
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "16000",
                            "-c:a", "pcm_s16le", str(dst)], check=True)
        with wave.open(str(dst)) as w:
            seconds = w.getnframes() / w.getframerate()
        refs[name] = {"words": song_reference(lyric, syl, notes), "onsets": [n[0] for n in notes], "seconds": seconds}
    (out / "refs.json").write_text(json.dumps(refs))
    words = [w for r in refs.values() for w in r["words"]]
    print(f"{len(refs)} recordings, {sum(r['seconds'] for r in refs.values()) / 60:.1f} min, {len(words)} words, "
          f"{sum(w['exact'] for w in words)} on lines whose syllables split exactly")


def model_dir(home, runtime, model):
    return pathlib.Path(home) / f"{runtime}-{model}"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def cmd_weights(a):
    for (runtime, model), spec in MODELS.items():
        d = model_dir(a.models, runtime, model)
        d.mkdir(parents=True, exist_ok=True)
        for name, (digest, size) in spec["files"].items():
            p = d / name
            if not p.exists():
                url = f"{HF}/{spec['repo']}/resolve/{spec['commit']}/{name}"
                subprocess.run(["curl", "-sSfL", "-o", str(p), url], check=True)
            ok = p.stat().st_size == size and (digest is None or sha256(p) == digest)
            print(f"{runtime} {model} {name}: {p.stat().st_size} bytes, {'ok' if ok else 'MISMATCH'} ({spec['format']})")
            if not ok:
                sys.exit(1)
        if spec["format"] == "npz":
            # numpy refuses pickled objects unless asked; every array must load without them.
            import numpy as np
            with np.load(d / "weights.npz", allow_pickle=False) as z:
                print(f"  npz: {len(z.files)} arrays, loaded with allow_pickle=False")


def run_mlx(model_path, wav, condition=True):
    # condition: Whisper's default, each 30 s window decoded with the text before it as its prompt.
    import mlx_whisper
    r = mlx_whisper.transcribe(str(wav), path_or_hf_repo=str(model_path), word_timestamps=True, language="en",
                               condition_on_previous_text=condition)
    return [{"text": w["word"], "start": w["start"], "end": w["end"]} for s in r["segments"] for w in s.get("words", [])]


# whisper.cpp's DTW presets, by model: word times from the cross-attention alignment heads.
DTW_PRESET = {"large-v3-turbo": "large.v3.turbo", "small.en": "small.en"}


def run_cpp(model_path, wav, cli, tmp, dtw=None):
    # One word a segment: whisper.cpp's own word times (token timestamps), or with `dtw` those of DTW.
    # DTW needs flash attention off (-nfa), and its times (t_dtw, in centiseconds) are only in the full JSON.
    prefix = tmp / wav.stem
    extra = ["-ojf", "-nfa", "--dtw", dtw] if dtw else ["-oj"]
    subprocess.run([str(cli), "-m", str(model_path), "-f", str(wav), "-l", "en", "-ml", "1", "-sow",
                    "-of", str(prefix), "-np", *extra], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    data = json.loads(prefix.with_suffix(".json").read_text(errors="replace"))
    words = []
    for s in data["transcription"]:
        if not s["text"].strip():
            continue
        start, end = s["offsets"]["from"] / 1000, s["offsets"]["to"] / 1000
        if dtw:
            times = [t["t_dtw"] / 100 for t in s.get("tokens", []) if t.get("t_dtw", -1) >= 0 and not t["text"].startswith("[_")]
            if not times:
                raise RuntimeError(f"{wav.name}: no DTW time for {s['text']!r}")
            start = times[0]
        words.append({"text": s["text"], "start": start, "end": end})
    return words


def hyp_words(raw):
    """Whisper's words, normalized: a word that normalizes to several ('1st', 'A-B') shares its times."""
    out = []
    for w in raw:
        for x in normalize(w["text"]):
            out.append({"w": x, "start": w["start"], "end": w["end"]})
    return out


def cmd_run(a):
    out = pathlib.Path(a.out)
    names = sorted(json.loads((out / "refs.json").read_text()))[: a.limit or None]
    key = (a.runtime, a.model)
    path = model_dir(a.models, *key)
    if a.runtime == "cpp":
        path = path / next(iter(MODELS[key]["files"]))
    tmp = out / "tmp"
    tmp.mkdir(exist_ok=True)
    dtw = DTW_PRESET[a.model] if a.dtw else None
    if a.no_condition and a.runtime != "mlx":
        sys.exit("--no-condition is for mlx only")
    go = (lambda wav: run_mlx(path, wav, not a.no_condition)) if a.runtime == "mlx" else (lambda wav: run_cpp(path, wav, a.whisper_cli, tmp, dtw))
    try:
        go(out / "wav16" / f"{names[0]}.wav")  # warm-up: the model loaded once, untimed
    except subprocess.CalledProcessError:
        pass  # the timed pass below runs it again and keeps the failure
    results, total = {}, 0.0
    for name in names:
        t = time.perf_counter()
        try:
            raw = go(out / "wav16" / f"{name}.wav")
        except subprocess.CalledProcessError as e:
            # whisper.cpp can abort on a recording (v1.9.5 with --dtw large.v3.turbo: SIGABRT, no message):
            # kept as a finding, left out of the scores and of the run's time, and the run goes on.
            took = time.perf_counter() - t
            results[name] = {"error": f"exit {e.returncode}", "seconds": took}
            print(f"{name}: failed, exit {e.returncode}", flush=True)
            continue
        took = time.perf_counter() - t
        total += took
        results[name] = {"raw": raw, "seconds": took}
        print(f"{name}: {took:.1f} s, {len(raw)} words", flush=True)
    label = a.runtime + ("-dtw" if dtw else "") + ("-nocond" if a.no_condition else "")
    dest = out / "runs" / f"{label}-{a.model}.json"
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps({"runtime": label, "model": a.model, "recordings": results, "seconds": total}))
    failed = sum("error" in v for v in results.values())
    print(f"{label} {a.model}: {total:.0f} s for {len(names) - failed} recordings" + (f", {failed} failed" if failed else ""))


def cmd_score(a):
    out = pathlib.Path(a.out)
    refs = json.loads((out / "refs.json").read_text())
    results = {}
    for run in sorted((out / "runs").glob("*.json")):
        r = json.loads(run.read_text())
        done = {n: v for n, v in r["recordings"].items() if "error" not in v}
        recs = [score_recording(refs[n]["words"], refs[n]["onsets"], hyp_words(v["raw"])) for n, v in done.items()]
        audio = sum(refs[n]["seconds"] for n in done)
        results[run.stem] = summarize(recs, audio, sum(v["seconds"] for v in done.values()),
                                      failed=len(r["recordings"]) - len(done))
        results[run.stem]["per_recording"] = {n: round((x["sub"] + x["del"] + x["ins"]) / x["ref"], 3)
                                              for n, x in zip(done, recs)}
    (out / "results.json").write_text(json.dumps(results, indent=1))
    cmd_table(a)


def cmd_table(a):
    results = json.loads((pathlib.Path(a.out) / "results.json").read_text())
    pct = lambda x: "-" if x is None else f"{100 * x:.1f}%"
    num = lambda x: "-" if x is None else f"{x:.1f}"
    ms = lambda x: "-" if x is None else f"{1000 * x:+.0f}" if x < 0 else f"{1000 * x:.0f}"
    print("| Run | Recordings (failed) | Words | WER | Sub / del / ins | WER per recording (median, worst) | Seconds per minute sung |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for k, r in results.items():
        print(f"| {k} | {r['recordings']} ({r.get('failed', 0)}) | {r['words']} | {pct(r['wer'])} | {r['sub']} / {r['del']} / {r['ins']} | "
              f"{pct(r['wer_median_recording'])}, {pct(r['wer_worst_recording'])} | {num(r['seconds_per_minute'])} |")
    print()
    print("| Run | Words timed | Start - note (median, ms) | abs median | abs 90% | within 100 ms | within 250 ms | to nearest onset (abs median) | less the median: abs median, within 100 ms |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for k, r in results.items():
        print(f"| {k} | {r['timed_words']} | {ms(r['to_note_median'])} | {ms(r['to_note_abs_median'])} | "
              f"{ms(r['to_note_abs_p90'])} | {pct(r['within_100ms'])} | {pct(r['within_250ms'])} | {ms(r['to_onset_abs_median'])} | "
              f"{ms(r['shifted_abs_median'])}, {pct(r['shifted_within_100ms'])} |")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refs")
    r.add_argument("--csd", required=True, help="the CSD folder (holding english/)")
    r.add_argument("--out", required=True)
    w = sub.add_parser("weights")
    w.add_argument("--models", required=True)
    x = sub.add_parser("run")
    x.add_argument("--runtime", choices=("mlx", "cpp"), required=True)
    x.add_argument("--model", choices=("large-v3-turbo", "small.en"), required=True)
    x.add_argument("--models", required=True)
    x.add_argument("--out", required=True)
    x.add_argument("--whisper-cli", default=None)
    x.add_argument("--dtw", action="store_true", help="whisper.cpp only: word times by DTW")
    x.add_argument("--no-condition", action="store_true",
                   help="mlx only: decode each window without the text before it (condition_on_previous_text=False)")
    x.add_argument("--limit", type=int, default=0)
    s = sub.add_parser("score")
    s.add_argument("--out", required=True)
    t = sub.add_parser("table")
    t.add_argument("--out", required=True)
    a = p.parse_args(argv)
    {"refs": cmd_refs, "weights": cmd_weights, "run": cmd_run, "score": cmd_score, "table": cmd_table}[a.cmd](a)


if __name__ == "__main__":
    main()
