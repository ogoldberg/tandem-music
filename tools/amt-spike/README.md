# AMT.0 spike: the Anticipatory Music Transformer

`spike.py` gives Stanford's Anticipatory Music Transformer the melody of `tests/fixtures/notation-project.json` (looped to 30 s) as anticipated controls, the notes it must write around and never changes, and scores the accompaniment it writes: in the key, consonant with the melody note sounding, and sharing a triad of the key with it, against its own melody and against the same melody a tritone up as the control. `harmony.js`'s own chords and bass for the same melody are scored the same way (`baseline`). `render.py` plays the results through the studio's own Export WAV, with the recorded General MIDI samples. The verdict and the numbers are in `docs/AUDIO.md` (Anticipatory Music Transformer, AMT.0). Nothing in Tandem imports this folder, and nothing is played aloud.

It runs in a virtual environment of its own, with the models anywhere you like (about 5.1 GB for the three sizes, plus 1.95 GB for the small and medium models converted to safetensors):

```bash
SPIKE=/path/to/a/folder/with/space
git clone https://github.com/jthickstun/anticipation.git "$SPIKE/src"
git -C "$SPIKE/src" checkout af37397922665a0fb8d474d7988b0f3755a38d45
python3.12 -m venv "$SPIKE/venv"
"$SPIKE/venv/bin/pip" install torch==2.15.0 transformers==5.22.2 safetensors==0.8.0 tqdm numpy mido
# Its requirements.txt pins transformers 4.29.2 and matplotlib; generating needs neither.
"$SPIKE/venv/bin/pip" install --no-deps "$SPIKE/src"

# The weights, at the revisions measured (stanford-crfm on Hugging Face, Apache 2.0):
#   music-small-800k  fa800530aa1126dd6b58b38f3bdb8fcec9c9d4f5  pytorch_model.bin  512,433,185 bytes
#   music-medium-800k 93b6eb7e09bad33be6cb2ebd50ce5279cbfde7f6  pytorch_model.bin  1,438,866,529 bytes
#   music-large-800k  e206a88d4658661c2757573eae724d5b27213824  model.safetensors  3,120,598,456 bytes
for m in music-small-800k:fa800530aa1126dd6b58b38f3bdb8fcec9c9d4f5 music-medium-800k:93b6eb7e09bad33be6cb2ebd50ce5279cbfde7f6; do
  name=${m%%:*}; rev=${m##*:}; mkdir -p "$SPIKE/w/$name"
  for f in config.json pytorch_model.bin; do curl -sSL -o "$SPIKE/w/$name/$f" "https://huggingface.co/stanford-crfm/$name/resolve/$rev/$f"; done
done
mkdir -p "$SPIKE/w/music-large-800k"
for f in config.json model.safetensors; do
  curl -sSL -o "$SPIKE/w/music-large-800k/$f" "https://huggingface.co/stanford-crfm/music-large-800k/resolve/e206a88d4658661c2757573eae724d5b27213824/$f"
done
shasum -a 256 "$SPIKE"/w/*/pytorch_model.bin "$SPIKE"/w/*/model.safetensors   # against the LFS hashes the Hugging Face API lists

# Small and medium: one load of the pickle with torch.load(weights_only=True), written as safetensors
# beside it; the run then loads safetensors only. Prints the largest logit difference (0.0 measured).
for name in music-small-800k music-medium-800k; do
  "$SPIKE/venv/bin/python" -I tools/amt-spike/spike.py convert --model "$SPIKE/w/$name"
done

"$SPIKE/venv/bin/python" -I tools/amt-spike/spike.py baseline --out "$SPIKE/out"
for model in music-small-800k/safetensors music-medium-800k/safetensors music-large-800k; do
  for variant in "--band --prompt-bars 1" "--band --no-rests" "--prompt-bars 1"; do
    "$SPIKE/venv/bin/python" -I tools/amt-spike/spike.py run --model "$SPIKE/w/$model" --device mps $variant --out "$SPIKE/out"
  done
  "$SPIKE/venv/bin/python" -I tools/amt-spike/spike.py run --model "$SPIKE/w/$model" --device cpu --band --prompt-bars 1 --seeds 0 --out "$SPIKE/out"
done
python3 tools/amt-spike/spike.py table --out "$SPIKE/out"

# WAVs to listen to, with the repository's own environment (requirements-dev.txt + requirements-e2e.txt):
.venv/bin/python tools/amt-spike/render.py "$SPIKE/wav" "$SPIKE"/out/music-*-mps-*-seed0.json
```

Each run writes, per seed and input (the notes, and the tritone), a Tandem project (`.json`: the melody, the pitched notes it wrote as the harmony part on piano, its drums as kick, snare and hat) and a MIDI file with every instrument it chose, and `results-<model>-<device>-<variant>.json` with the scores and times. The variants: `--band` lets it write only piano, fingered bass and drums (else any of the 129 instruments); `--no-rests` never samples the rest token; `--prompt-bars N` starts it from `harmony.js`'s chords and bass for the first N bars and scores only what it writes after them. `--seeds`, `--seconds` and `--top-p` (0.95) change the run.
