#!/usr/bin/env python3
"""Render the self-hosted General MIDI samples (SND.1) from the FluidR3_GM SoundFont.

    python tools/gm-samples/build.py           # rebuild vendor/gm-samples-1
    python tools/gm-samples/build.py --check   # rebuild in a temp dir and fail if the
                                               # committed files differ

Needs FluidSynth (`fluidsynth`) and LAME (`lame`) on PATH, plus numpy. The SoundFont comes
from Debian's fluid-soundfont-gm package; the .deb and the .sf2 inside it are checked against
the SHA-256 hashes below before anything is rendered. Each instrument is rendered dry (no
reverb or chorus) at one root note every 3 semitones, so no note inside the range is
pitch-shifted by more than 1 semitone, at velocity 100, mono, 22,050 Hz (the WAV export's rate), then encoded
as MP3. The kick, snare and closed hi-hat come from the SoundFont's standard drum kit.

Output: one MP3 per root (`<instrument>/<midi>.mp3`), `manifest.json` (programs, roots, levels
and loop points, read by samples.js), `LICENSES.txt` and `SHA256SUMS` (checked by
tests/test_api.py against the served bytes). The build is deterministic for given FluidSynth
and LAME versions, which are recorded in the manifest; --check only matches when they are the
same as the committed build's.
"""
import hashlib
import io
import json
import lzma
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
DEST = REPO / "vendor" / "gm-samples-1"
DEB_URL = "https://deb.debian.org/debian/pool/main/f/fluid-soundfont/fluid-soundfont-gm_3.1-6_all.deb"
DEB_SHA256 = "9965fbcc6acee17d6f72b685d28c7f968ec64eba14645445b476d5c6cc2eee4c"
SF2_MEMBER = "./usr/share/sounds/sf2/FluidR3_GM.sf2"
COPYRIGHT_MEMBER = "./usr/share/doc/fluid-soundfont-gm/copyright"
RATE = 22050
VELOCITY = 100
# Peak level of the loudest sample of each instrument after normalisation.
PEAK = 0.89
# Instrument name -> General MIDI program (0-based), lowest and highest root, how long the key
# is held (s), and whether the sound sustains while held (looped in the browser for notes longer
# than `hold`; loop points are sample offsets at RATE) or dies away by itself (cut once it is 60 dB below the instrument's peak).
INSTRUMENTS = {
    "piano":   {"program": 0,  "name": "Acoustic Grand Piano",   "low": 24, "high": 105, "hold": 4.0, "sustains": False},
    "marimba": {"program": 12, "name": "Marimba",                "low": 36, "high": 96,  "hold": 2.0, "sustains": False},
    "strings": {"program": 48, "name": "String Ensemble 1",      "low": 27, "high": 96,  "hold": 3.0, "sustains": True},
    "bass":    {"program": 33, "name": "Electric Bass (finger)", "low": 24, "high": 72,  "hold": 3.0, "sustains": False},
    "chip":    {"program": 80, "name": "Lead 1 (square)",        "low": 24, "high": 96,  "hold": 2.0, "sustains": True},
    "organ":   {"program": 16, "name": "Drawbar Organ",          "low": 24, "high": 96,  "hold": 2.0, "sustains": True},
    "guitar":  {"program": 24, "name": "Acoustic Guitar (nylon)", "low": 36, "high": 87, "hold": 3.0, "sustains": False},
    "flute":   {"program": 73, "name": "Flute",                  "low": 48, "high": 99,  "hold": 3.0, "sustains": True},
}
STEP = 3
# Drum name -> General MIDI percussion key (channel 10, standard kit).
DRUMS = {"kick": 36, "snare": 38, "hat": 42}
DRUM_HOLD = 1.0
SILENT_DB = -60


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def fetch_sf2(work):
    """Download the Debian package, check its hash, and return (sf2 bytes, copyright text)."""
    cache = Path(os.environ.get("GM_SAMPLES_DEB", work / "fluid.deb"))
    if not cache.exists():
        with urllib.request.urlopen(DEB_URL, timeout=120) as r:
            cache.write_bytes(r.read())
    deb = cache.read_bytes()
    if sha256(deb) != DEB_SHA256:
        raise SystemExit(f"{cache}: SHA-256 {sha256(deb)} does not match {DEB_SHA256}")
    # A .deb is an ar archive; the files are in data.tar.xz.
    if deb[:8] != b"!<arch>\n":
        raise SystemExit("not an ar archive")
    pos, data = 8, None
    while pos < len(deb):
        name = deb[pos:pos + 16].decode().strip().rstrip("/")
        size = int(deb[pos + 48:pos + 58].decode().strip())
        body = deb[pos + 60:pos + 60 + size]
        if name == "data.tar.xz":
            data = body
        pos += 60 + size + (size & 1)
    if data is None:
        raise SystemExit("data.tar.xz not found in the package")
    with tarfile.open(fileobj=io.BytesIO(lzma.decompress(data))) as tar:
        sf2 = tar.extractfile(SF2_MEMBER).read()
        copyright_text = tar.extractfile(COPYRIGHT_MEMBER).read().decode()
    return sf2, copyright_text


def vlq(n):
    out = [n & 0x7F]
    while n > 0x7F:
        n >>= 7
        out.insert(0, (n & 0x7F) | 0x80)
    return bytes(out)


def midi_file(channel, program, key, hold, tail):
    """A one-note type-0 MIDI file: 1000 ticks per beat at 60 bpm, so 1 tick = 1 ms."""
    ms = lambda s: int(round(s * 1000))
    ev = b""
    ev += vlq(0) + bytes([0xFF, 0x51, 3]) + (1_000_000).to_bytes(3, "big")
    ev += vlq(0) + bytes([0xC0 | channel, program])
    ev += vlq(0) + bytes([0x90 | channel, key, VELOCITY])
    ev += vlq(ms(hold)) + bytes([0x80 | channel, key, 0])
    ev += vlq(ms(tail)) + bytes([0xFF, 0x2F, 0])
    return (b"MThd" + struct.pack(">IHHH", 6, 0, 1, 1000)
            + b"MTrk" + struct.pack(">I", len(ev)) + ev)


def render(sf2_path, work, channel, program, key, hold, tail=0.3):
    mid = work / "note.mid"
    raw = work / "note.raw"
    mid.write_bytes(midi_file(channel, program, key, hold, tail))
    subprocess.run(
        ["fluidsynth", "-n", "-i", "-q", "-R", "0", "-C", "0", "-g", "0.5", "-r", str(RATE),
         "-O", "float", "-E", "little", "-T", "raw", "-F", str(raw), str(sf2_path), str(mid)],
        check=True, stdout=subprocess.DEVNULL)
    stereo = np.frombuffer(raw.read_bytes(), "<f4").reshape(-1, 2).astype(np.float64)
    return stereo.mean(axis=1)


def find_loop(x, hold):
    """Loop points (s) inside the held part of a sustained note. The end is just before the key
    is released; the start is the point at least 0.4 s earlier (and after the attack, from 0.5 s)
    whose preceding waveform best matches the waveform before the end. Returns (start, end,
    score), score being that match's normalised correlation."""
    end = int((hold - 0.05) * RATE)
    n = 512
    tail = x[end - n:end]
    best, best_score = None, -2.0
    for start in range(int(0.5 * RATE), end - int(0.4 * RATE)):
        seg = x[start - n:start]
        denom = np.linalg.norm(seg) * np.linalg.norm(tail)
        score = float(seg @ tail / denom) if denom > 0 else -1.0
        if score > best_score:
            best, best_score = start, score
    return best, end, best_score


XFADE = 0.1


def crossfade_loop(x, start, end, score):
    """Blend the last XFADE s before the loop end into the XFADE s before the loop start, so the
    sample just before `end` equals the one just before `start` and the jump back is seamless
    for any sound, periodic or not (a detuned string ensemble never repeats exactly). Matching
    waveforms add in phase, so they get linear fades; unrelated ones get equal-power fades."""
    f = int(XFADE * RATE)
    t = np.linspace(0, 1, f, endpoint=False)
    fade_in, fade_out = (t, 1 - t) if score >= 0.9 else (np.sin(t * np.pi / 2), np.cos(t * np.pi / 2))
    x = x.copy()
    x[end - f:end] = x[end - f:end] * fade_out + x[start - f:start] * fade_in
    return x


def trim(x, peak, sustains, hold):
    """Cut a decaying sound once it stays below SILENT_DB relative to `peak`; a sustained one at
    the key release. Ends with a 10 ms fade so the cut never clicks."""
    if sustains:
        end = int(hold * RATE)
    else:
        loud = np.nonzero(np.abs(x[:int(hold * RATE)]) > peak * 10 ** (SILENT_DB / 20))[0]
        end = int(loud[-1]) + 1 if len(loud) else int(0.05 * RATE)
    x = x[:end].copy()
    fade = min(len(x), int(0.01 * RATE))
    x[len(x) - fade:] *= np.linspace(1, 0, fade)
    return x


def encode(x, path, work):
    wav = work / "note.wav"
    pcm = np.round(np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()
    header = (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
              + struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * 2, 2, 16)
              + b"data" + struct.pack("<I", len(pcm)))
    wav.write_bytes(header + pcm)
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["lame", "--silent", "-m", "m", "-b", "64", "--noreplaygain", str(wav), str(path)], check=True)


def version(cmd):
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    return out.splitlines()[0].strip() if out else "unknown"


def build(out, work):
    sf2, copyright_text = fetch_sf2(work)
    sf2_path = work / "FluidR3_GM.sf2"
    sf2_path.write_bytes(sf2)
    manifest = {
        "format": "tandem-gm-samples",
        "version": 1,
        "source": {"soundfont": "FluidR3_GM.sf2", "sha256": sha256(sf2), "package": DEB_URL,
                   "package_sha256": DEB_SHA256, "license": "MIT"},
        "renderer": {"fluidsynth": version(["fluidsynth", "--version"]), "lame": version(["lame", "--version"])},
        "sample_rate": RATE,
        "velocity": VELOCITY,
        "instruments": {},
        "drums": {},
    }
    for name, spec in INSTRUMENTS.items():
        roots = list(range(spec["low"], spec["high"] + 1, STEP))
        raw = {m: render(sf2_path, work, 0, spec["program"], m, spec["hold"]) for m in roots}
        peak = max(np.abs(x).max() for x in raw.values())
        scale = PEAK / peak
        entry = {"program": spec["program"], "name": spec["name"], "sustains": spec["sustains"], "samples": {}}
        for m, x in raw.items():
            sample = {"file": f"{name}/{m}.mp3"}
            if spec["sustains"]:
                start, end, score = find_loop(x, spec["hold"])
                x = crossfade_loop(x, start, end, score)
                sample["loop"] = [start, end]
            encode(trim(x, peak, spec["sustains"], spec["hold"]) * scale, out / sample["file"], work)
            entry["samples"][str(m)] = sample
        manifest["instruments"][name] = entry
    raw = {k: render(sf2_path, work, 9, 0, key, DRUM_HOLD) for k, key in DRUMS.items()}
    peak = max(np.abs(x).max() for x in raw.values())
    for k, x in raw.items():
        manifest["drums"][k] = {"key": DRUMS[k], "file": f"drums/{k}.mp3"}
        encode(trim(x, peak, False, DRUM_HOLD) * (PEAK / peak), out / f"drums/{k}.mp3", work)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    (out / "LICENSES.txt").write_text(
        "Samples rendered from FluidR3_GM.sf2 (Frank Wen) by tools/gm-samples/build.py.\n"
        f"Source: {DEB_URL}\n\n==== Debian copyright file ====\n\n{copyright_text}")
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    (out / "SHA256SUMS").write_text("".join(f"{sha256((out / f).read_bytes())}  {f}\n" for f in files))


def main():
    check = "--check" in sys.argv[1:]
    with tempfile.TemporaryDirectory() as tmp:
        work, out = Path(tmp) / "work", Path(tmp) / "out"
        work.mkdir()
        out.mkdir()
        build(out, work)
        if check:
            r = subprocess.run(["diff", "-r", str(out), str(DEST)])
            if r.returncode:
                raise SystemExit("vendor/gm-samples-1 differs from a fresh build")
            print("vendor/gm-samples-1 matches a fresh build")
        else:
            shutil.rmtree(DEST, ignore_errors=True)
            shutil.copytree(out, DEST)
            total = sum(p.stat().st_size for p in DEST.rglob("*") if p.is_file())
            print(f"wrote {DEST.relative_to(REPO)}: {len(list(DEST.rglob('*.mp3')))} samples, {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
