# PITCH.0 spike: RMVPE and PESTO against YIN and Basic Pitch's contour

`spike.py` makes the clips with their true pitch (VOX.1's sung phrase at four rates in four variants, white noise alone, and SEP.1's fixture voice alone, in the mix and separated by HTDemucs), runs the Python trackers over them, and scores every tracker's readings against the truth. `yin_live.mjs` runs the live guide's own tracker (`pitch.js`) in Node, and `browser.py` runs Basic Pitch's contour and PESTO in ONNX Runtime Web in headless Chromium against the app's own server. The verdict and the numbers are in `docs/AUDIO.md` (Pitch trackers, PITCH.0). Nothing in Tandem imports this folder, and nothing is played aloud. `tests/test_pitch_spike.py` checks the truth and the scoring.

Four environments: the repository's `.venv` (requirements-dev.txt and requirements-e2e.txt), one with `requirements-models.txt` for HTDemucs, a spike environment for RMVPE and PESTO, and Node 22.

```bash
SPIKE=/path/to/a/folder/with/space   # about 1.9 GB with everything below
REPO=$PWD

# The spike environment. PESTO runs from a checkout on the path: its PyPI wheel 2.0.1 has no weights and
# no streaming mode, and the repository's pyproject installs `pesto` without `pesto.utils`.
python3.12 -m venv "$SPIKE/venv"
"$SPIKE/venv/bin/pip" install torch==2.15.0 torchaudio==2.11.1 onnxruntime==1.32.0 onnx==1.23.2 onnxscript==0.7.2 \
  librosa==1.0.1 omegaconf==2.4.0 tqdm soundfile numpy scipy
git clone https://github.com/SonyCSLParis/pesto.git "$SPIKE/pesto-src"
git -C "$SPIKE/pesto-src" checkout 62bc0c9702558f19af4593752947fb9db1eadac9
# RMVPE's ONNX weights (lj1995/VoiceConversionWebUI, tagged MIT): 361,688,443 bytes,
# SHA-256 5370e71ac80af8b4b7c793d27efd51fd8bf962de3a7ede0766dac0befa3660fd
mkdir -p "$SPIKE/w"
curl -sSL -o "$SPIKE/w/rmvpe.onnx" https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/e6d0c1a17da07c33557852f9dfa2bd44cc75737d/rmvpe.onnx
shasum -a 256 "$SPIKE/w/rmvpe.onnx"
# ONNX Runtime Web for the browser run (npm onnxruntime-web 1.31.1, MIT):
curl -sSL https://registry.npmjs.org/onnxruntime-web/-/onnxruntime-web-1.31.1.tgz | (mkdir -p "$SPIKE/ort-web" && tar -xz -C "$SPIKE/ort-web")

# The clips and their truth (the repository's .venv).
.venv/bin/python tools/pitch-spike/spike.py clips --out "$SPIKE/out"
# SEP.1's mix through HTDemucs, as the Mac app runs it: MODEL.1's runtime downloads and hash-checks the weights
# into the model home. Any environment with requirements-models.txt.
/path/to/models-venv/bin/python tools/pitch-spike/spike.py separate --out "$SPIKE/out" --model-home "$SPIKE/model-home"

# PESTO's streaming model as ONNX, one 10 ms step per call (22,050 Hz does not export: its 220-sample step is
# shorter than PESTO's lowest CQT kernel). Prints the largest difference to PyTorch over 200 steps.
for r in 16000 44100 48000; do
  "$SPIKE/venv/bin/python" tools/pitch-spike/spike.py export --pesto-src "$SPIKE/pesto-src" --onnx-dir "$SPIKE/onnx" --rate $r
done

# The trackers, one at a time so their times do not disturb each other.
.venv/bin/python tools/pitch-spike/spike.py track --tracker yin-bench --out "$SPIKE/out"
node tools/pitch-spike/yin_live.mjs "$SPIKE/out"
"$SPIKE/venv/bin/python" tools/pitch-spike/spike.py track --tracker rmvpe --weights "$SPIKE/w/rmvpe.onnx" --out "$SPIKE/out"
"$SPIKE/venv/bin/python" tools/pitch-spike/spike.py track --tracker pesto --threshold 0.2 --pesto-src "$SPIKE/pesto-src" --out "$SPIKE/out"
"$SPIKE/venv/bin/python" tools/pitch-spike/spike.py track --tracker pesto-stream --threshold 0.1 --onnx-dir "$SPIKE/onnx" --out "$SPIKE/out"
.venv/bin/python tools/pitch-spike/browser.py --threshold 0.1 --out "$SPIKE/out" --ort "$SPIKE/ort-web/package/dist" --onnx-dir "$SPIKE/onnx"

# What the weight files are and whether torch.load(weights_only=True) takes the PESTO checkpoints.
"$SPIKE/venv/bin/python" tools/pitch-spike/spike.py weights "$SPIKE/w/rmvpe.onnx" "$SPIKE"/pesto-src/pesto/weights/*.ckpt

# Scores, the tables in docs/AUDIO.md, and PESTO's voicing at other confidence thresholds.
python3 tools/pitch-spike/spike.py score --out "$SPIKE/out"
python3 tools/pitch-spike/spike.py table --out "$SPIKE/out"
python3 tools/pitch-spike/spike.py sweep --tracker pesto --out "$SPIKE/out" --thresholds 0.02 0.05 0.1 0.2 0.3 0.5
python3 tools/pitch-spike/spike.py sweep --tracker pesto-stream --out "$SPIKE/out" --thresholds 0.02 0.05 0.1 0.2 0.3 0.5
```

`out/clips/` holds each clip as a 16-bit WAV with `<clip>.truth.json` (the true MIDI pitch every 5 ms, `null` where nothing is sung); `out/tracks/<tracker>/<clip>.json` holds a tracker's readings (time, MIDI or `null`, PESTO's confidence) and its compute time; `out/results.json` the scores. The sweep scores voicing only, from the confidences a track kept, so it works after a track at any threshold.
