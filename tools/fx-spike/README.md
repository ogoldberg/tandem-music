# FX.0 spike: the MPC Plugin SDK's DSP as WebAssembly in an AudioWorklet

`stereo_delay.cpp` is the SDK's `StereoDelay` example (inMusic's MIT-licensed MPC Plugin SDK, https://github.com/inmusic-software/mpc-plugin-builder-sdk, commit `febd2ca`) without the `mpc::Plugin` host layer: the same per-block and per-sample code, its `framework/dsp/` headers unchanged, behind a small C API. `build.sh` compiles it to a standalone `delay.wasm` (no Emscripten JS glue, no imports) and to a native `fx-native` with the same flags. `spike.py run` renders SEP.1's fixture voice and a lone impulse through the native build, the WebAssembly in Node (`wasm_node.mjs`) and the WebAssembly in an AudioWorklet (`worklet.js`) in headless Chromium's OfflineAudioContext, compares them sample by sample, checks the echoes, and times each engine. The verdict and the numbers are in `docs/AUDIO.md` (Audio effects, FX.0). Nothing in Tandem imports this folder, and nothing is played aloud. `tests/test_fx_spike.py` checks the comparison and echo finding, and builds and compares the two engines where Emscripten 7.0.0 is installed.

```bash
OUT=/path/to/a/scratch/folder
# Emscripten 7.0.0 (the VOX.4 setup: brew install emscripten), Xcode's clang++, Node 22, the
# repository's .venv with requirements-dev.txt and requirements-e2e.txt (Playwright's Chromium).
bash tools/fx-spike/build.sh "$OUT/build"
.venv/bin/python tools/fx-spike/spike.py run --build "$OUT/build" --out "$OUT/run"
# $OUT/run/results.json holds every comparison, echo time and timing; voice-*-native.wav and
# voice-*-worklet.wav are the renders to listen to.
```
