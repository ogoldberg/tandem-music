# MRT.0 spike: Magenta RealTime 2

`spike.py` renders the melody and harmony of `tests/fixtures/notation-project.json` as Magenta RealTime 2's piano roll with a style in words, with the exported MLX model, one 40 ms frame at a time, and measures how closely the music follows the notes and how long it takes. The verdict and the numbers are in `docs/AUDIO.md` (Magenta RealTime 2, MRT.0). Nothing in Tandem imports this folder.

It runs in a virtual environment of its own, on Apple silicon, with the models anywhere you like (`MAGENTA_HOME`; about 4.6 GB for both exported models and the shared resources):

```bash
SPIKE=/path/to/a/folder/with/space
python3.12 -m venv "$SPIKE/venv"
"$SPIKE/venv/bin/pip" install "magenta-rt[mlx]==2.0.3" "mlx==0.31.1" "mlx-metal==0.31.1"
# The .mlxfn files at this revision were exported with MLX 0.31.1; MLX 0.32 refuses them
# ("[import_function] Invalid string size").
HF_HOME="$SPIKE/hf" "$SPIKE/venv/bin/python" -c "
import huggingface_hub as h
h.snapshot_download('google/magenta-realtime-2', revision='$(curl -s https://huggingface.co/api/models/google/magenta-realtime-2 | python3 -c "import json,sys;print(json.load(sys.stdin)['sha'])")',
                    local_dir='$SPIKE/magenta/magenta-rt-v2', allow_patterns=['resources/*', 'models/*'])"

for model in mrt2_small mrt2_base; do
  MAGENTA_HOME="$SPIKE/magenta" HF_HUB_OFFLINE=1 "$SPIKE/venv/bin/python" -I tools/mrt-spike/spike.py \
    --model $model --out "$SPIKE/out"
done
```

Each run writes two 30 s WAVs (the notes, and the same notes a tritone up), scores each against its own notes, the other notes and its own notes two bars later, and writes `results-<model>-cfg<n>.json` to `--out`. `--manifest` adds the size and SHA-256 of every model file. `--style`, `--cfg-notes`, `--no-drums`, `--seed` and `--seconds` change the run.
