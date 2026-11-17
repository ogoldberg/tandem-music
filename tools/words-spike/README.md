# WORDS.0 spike: Whisper for sung lyrics, with word times against the notes

`spike.py` asks whether Whisper can hear the words of a sung melody well enough, and time each word closely enough, for Tandem to use them. Two things are measured: the word error rate against the words that were sung, and each word's start against the start of the note its first syllable is sung on. It runs two runtimes and two models: mlx-whisper (word times from Whisper's cross-attention, as OpenAI's `word_timestamps`), whisper.cpp with its own token timestamps, and whisper.cpp with its DTW word times; each with `large-v3-turbo` and `small.en`. The verdict and the numbers are in `docs/AUDIO.md` (Sung words, WORDS.0). Nothing in Tandem imports this folder, and nothing is played aloud. `tests/test_words_spike.py` checks the reference, the alignment and the scores.

## The data

The first pass uses the English half of the Children's Song Dataset (CSD 1.1, [Zenodo record 4916302](https://zenodo.org/records/4916302)): 50 children's songs, each sung twice (two keys) by one trained female singer, dry, recorded at 44.1 kHz, with the words of each line (`lyric/`), the syllables of each line (`txt/`) and every syllable's note (`csv/`: start, end, pitch, syllable). That is 100 recordings, 140.4 minutes, 11,431 words. Its licence is CC BY-NC-SA 4.0, for research: it stays outside the repository, is never redistributed, and nothing derived from it is shipped.

A word's note is found by splitting each line's syllables over its words: each word gets its estimated syllable count (vowel groups, less a silent final e or -ed), and a line is used for timing only when those estimates add up to exactly the line's syllables (8,502 words). Every word counts for the error rate. `en005a` and `en005b` have 18 lyric lines and 16 syllable lines, so each is read as one line.

## Running it

```bash
W=/path/to/a/folder/with/space   # about 7 GB with everything below
# From the repository root.

# The data: CSD 1.1 (1,851,131,390 bytes, SHA-256 0e64d7766f13bb9e9d5fd4486e234b71c540e2d8ecbe23594da0ad8d9697cd7c).
mkdir -p "$W/csd" && curl -sSfL -o "$W/csd/CSD.zip" "https://zenodo.org/records/4916302/files/CSD.zip?download=1"
shasum -a 256 "$W/csd/CSD.zip" && unzip -q "$W/csd/CSD.zip" -d "$W/csd"

# The spike environment (Python 3.12; mlx needs Apple silicon). ffmpeg converts the audio.
uv venv --python 3.12 "$W/venv"
uv pip install --python "$W/venv/bin/python" mlx-whisper==0.4.3 mlx==0.32.4 numpy

# whisper.cpp v1.9.5 (commit d1be6fde11ac6e0407606b4e42fe72d34add8037), built with Metal.
git clone --branch v1.9.5 https://github.com/ggml-org/whisper.cpp "$W/whisper.cpp"
cmake -S "$W/whisper.cpp" -B "$W/whisper.cpp/build" -DCMAKE_BUILD_TYPE=Release -DGGML_METAL=ON
cmake --build "$W/whisper.cpp/build" -j --config Release --target whisper-cli

P="$W/venv/bin/python"; S=tools/words-spike/spike.py

# The weights, each pinned to one commit by size and SHA-256 in spike.py MODELS (about 4.2 GB). The small.en
# npz is loaded with allow_pickle=False.
"$P" -I $S weights --models "$W/models"

# The reference and the 16 kHz mono WAVs both runtimes read.
"$P" -I $S refs --csd "$W/csd/CSD" --out "$W/out"

# Six runs (seven with the one below), one process each; each loads its model and transcribes the first recording once, untimed.
export HF_HOME="$W/hf"
for m in large-v3-turbo small.en; do
  "$P" -I $S run --runtime mlx --model $m --models "$W/models" --out "$W/out"
  "$P" -I $S run --runtime cpp --model $m --models "$W/models" --out "$W/out" --whisper-cli "$W/whisper.cpp/build/bin/whisper-cli"
  "$P" -I $S run --runtime cpp --dtw --model $m --models "$W/models" --out "$W/out" --whisper-cli "$W/whisper.cpp/build/bin/whisper-cli"
done
# And mlx large-v3-turbo with each 30 s window decoded without the text before it as its prompt.
"$P" -I $S run --runtime mlx --no-condition --model large-v3-turbo --models "$W/models" --out "$W/out"

# Every run against the reference: out/results.json and the two tables in docs/AUDIO.md.
"$P" -I $S score --out "$W/out"
```

`run --limit 2` runs only the first two recordings (the smoke test). When whisper-cli exits with an error on a recording, the run keeps `{"error": "exit <code>"}` for it and goes on; `score` leaves those recordings out of every number (and their time out of the speed) and counts them under Recordings (failed).

whisper.cpp is run one word a segment (`-ml 1 -sow`), English only (`-l en`). Its DTW word times need flash attention off (`-nfa`) and are only in the full JSON (`-ojf`), in centiseconds (`t_dtw`); the presets are `large.v3.turbo` and `small.en`.

`out/runs/<runtime>-<model>.json` holds every recording's words with their times and how long it took; `out/results.json` the scores, with each recording's error rate under `per_recording`.

## What it does not test

One trained singer, children's songs, clear diction, no accompaniment. It does not test the operator singing their own songs through headphones, everyday or untrained singing, singing over the song playing, or any language but English (the dataset's Korean half is not run).
