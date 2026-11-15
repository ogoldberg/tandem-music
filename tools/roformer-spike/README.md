# ROFORMER.0 spike: Mel-RoFormer and BS-RoFormer vocal separation against HTDemucs

`spike.py` makes the clips from SEP.1's fixture (`tests/separation_fixture.py`: the mix, the voice and the band it was made from, and the mix repeated to 3 minutes), checks and converts the RoFormer checkpoints, separates each clip with each model in a process of its own (its time and peak memory), and scores every separated vocal against the voice and the band. The verdict and the numbers are in `docs/AUDIO.md` (Voice separation, ROFORMER.0). Nothing in Tandem imports this folder, and nothing is played aloud. `tests/test_roformer_spike.py` checks the clips, the measures and the overlap-add.

The models, each pinned to one commit by URL, SHA-256 and size in `spike.py` `MODELS`:

| Model | Family | Weights | Licence |
| --- | --- | --- | --- |
| `kim-mel-roformer` | Mel-band RoFormer, Kim Vocal 2 (228 M parameters) | `KimberleyJSN/melbandroformer` `MelBandRoformer.ckpt`, 913 MB | MIT (relicensed from GPL-3.0 by its author on 2026-04-22, commit `ac9b061`) |
| `mel-roformer-small` | Mel-band RoFormer (51 M) | `Aname-Tommy/Mel_Band_Roformer_small` `mel_band_roformer_small.ckpt`, 203 MB | MIT (the model card's tag; nothing else said) |
| `anvuew-bs-roformer` | Band-split RoFormer (51 M) | `anvuew/BS-RoFormer` `bs_roformer_ft1_anvuew_sdr_12.55.ckpt`, 204 MB | GPL-3.0 |

Left out: viperx's BS-RoFormer (`model_bs_roformer_ep_317_sdr_12.9755.ckpt`, the one most tools use) states no licence anywhere upstream; `becruily`'s RoFormers state none either, and their `mel-band-roformer-deux` is CC-BY-NC 4.0; ZFTurbo's own vocal Mel-RoFormer was released a year before the repository's MIT licence was added.

The RoFormer classes come from ZFTurbo's Music-Source-Separation-Training (MIT) at a pinned commit; the overlap-add is its `demix` (generic mode) ported into `spike.py` in float32. HTDemucs runs through the Mac app's own code (`tandem_desktop/separation.py`, MODEL.1's download and hash check). The models are stereo: the mono clip goes in as both channels and the two output channels are averaged.

```bash
SPIKE=/path/to/a/folder/with/space   # about 3 GB with everything below
# From the repository root (its .python-version picks Python 3.12).

# The spike environment: torch and demucs as in requirements-models.txt, plus the RoFormer classes' packages.
python3.12 -m venv "$SPIKE/venv"
"$SPIKE/venv/bin/pip" install torch==2.15.0 demucs==4.1.0 safetensors==0.8.0 julius==0.2.8 einops==0.8.2 \
  rotary-embedding-torch==0.9.2 beartype==0.23.1 librosa==0.11.0 pyyaml==6.0.3 psutil==7.2.2 "httpx>=0.27,<1" \
  numpy scipy soundfile
git clone https://github.com/ZFTurbo/Music-Source-Separation-Training "$SPIKE/msst"
git -C "$SPIKE/msst" checkout 1f700c386e0dd763fe0a57242bb9420dce987354

# The checkpoints and the configurations that come with them (Kim's configuration is in the MSST checkout).
H=https://huggingface.co; mkdir -p "$SPIKE/w"
curl -sSL -o "$SPIKE/w/MelBandRoformer.ckpt" $H/KimberleyJSN/melbandroformer/resolve/ac9b0614ab3cd7f77219e18ba494dfd93956c348/MelBandRoformer.ckpt
curl -sSL -o "$SPIKE/w/mel_band_roformer_small.ckpt" $H/Aname-Tommy/Mel_Band_Roformer_small/resolve/1704b634bee2dd4d912f56c7b5c3cf952961cfb7/mel_band_roformer_small.ckpt
curl -sSL -o "$SPIKE/w/mel_band_roformer_small.yaml" $H/Aname-Tommy/Mel_Band_Roformer_small/resolve/1704b634bee2dd4d912f56c7b5c3cf952961cfb7/config.yaml
curl -sSL -o "$SPIKE/w/bs_roformer_ft1_anvuew_sdr_12.55.ckpt" $H/anvuew/BS-RoFormer/resolve/24988f47270cb3529b62c4f3bbb8234f4586de9b/bs_roformer_ft1_anvuew_sdr_12.55.ckpt
curl -sSL -o "$SPIKE/w/bs_roformer_anvuew.yaml" $H/anvuew/BS-RoFormer/resolve/24988f47270cb3529b62c4f3bbb8234f4586de9b/config.yaml

# The clips (the repository's .venv).
.venv/bin/python tools/roformer-spike/spike.py clips --out "$SPIKE/out"

# Each checkpoint against its pin, through torch.load(weights_only=True), written to safetensors and read back.
"$SPIKE/venv/bin/python" tools/roformer-spike/spike.py weights --weights "$SPIKE/w" --out "$SPIKE/out"

# Every model over every clip, one process each so the times and memory do not mix. HTDemucs is downloaded
# into the model home by MODEL.1's runtime the first time.
for m in htdemucs kim-mel-roformer mel-roformer-small anvuew-bs-roformer; do
  for run in "mix mps 8" "band mps 2" "song mps 1" "mix cpu 2" "song cpu 1"; do
    set -- $run
    "$SPIKE/venv/bin/python" tools/roformer-spike/spike.py separate --model $m --clip $1 --device $2 --runs $3 \
      --out "$SPIKE/out" --weights "$SPIKE/w" --msst "$SPIKE/msst" --model-home "$SPIKE/model-home"
  done
done

# Scores and the tables in docs/AUDIO.md (the .venv: melody recall uses the server's transcriber).
.venv/bin/python tools/roformer-spike/spike.py score --out "$SPIKE/out"
.venv/bin/python tools/roformer-spike/spike.py table --out "$SPIKE/out"
```

Run `k` of a clip separates it behind `k` times 37 ms of silence, cut off again afterwards: HTDemucs as the app calls it (`shifts=1`) shifts its input at random on every run, so one run's recall is one draw (the same mix gave 0.62 and 0.81 on two runs), and the runs give every model the same variants. Each process separates 2 s once before the timed runs (the first pass on Metal compiles its kernels).

`out/vocals/<model>/<clip>-<device>-<k>.wav` holds each separated vocal and `<clip>-<device>.json` the load time, the warm-up, each run's time and the peak memory (the process's resident peak from `getrusage`, and on Metal the driver's allocated memory sampled every 50 ms); `out/weights.json` the checkpoint checks; `out/results.json` the scores.
