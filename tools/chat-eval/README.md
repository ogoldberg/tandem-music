# Chat model evaluation (AI.5)

`chat_eval.py` asks a model the 18 fixed cases in `CASES` through the studio's own chat path in
`tandem_backend.py`: `chat_messages` (the project JSON, genre line and history the studio sends, and
for AI.6's five cases the song summary in `SONGS`, the one `actions.js` `songSummary` gives; the 13 cases
before AI.6 go without it so their scores compare with earlier runs),
`invoke_llm` (the system prompt, provider adapter and temperature 0.5) and `chat_plan` (JSON parse,
action allowlist and clamps, melody lock). Every answer is scored on:

- **JSON**: the answer parsed as a JSON object.
- **Valid actions**: no action the model wrote was dropped by the allowlist and checks.
- **Melody lock**: with the lock on (most cases), the model wrote no melody change, even a malformed
  one. The studio drops them anyway; this measures whether the model follows the prompt. A run with
  no answer (an error or timeout) is not scored on it.
- **Did what was asked**: the actions the studio would apply do what the request asked (each case's
  own check, such as a tempo of 125-135 for "about 130 BPM", or the melody's first seven notes
  unchanged for "delete the last note"). AI.6's `add_beat` is read as the studio plays it: the
  starter beat's hits (`GROOVE_BARS`, checked against `beats.js`), so "add a beat" passes with it.

plus seconds to answer and tokens in and out.

```bash
# Local, free: Ollama with its models on the external SSD (see docs/DEVELOPMENT.md)
OLLAMA_MODELS="/Volumes/Samsung SSD 990 PRO with Heatsink 2TB Media/tandem-ollama/models" ollama serve &
ollama pull qwen3:8b
~/m5-heavy.sh ai5 python tools/chat-eval/chat_eval.py run --provider ollama --model qwen3:8b --out runs.jsonl

# Paid: ask the operator first. The key comes from the environment variable named by --key-env.
python tools/chat-eval/chat_eval.py run --provider anthropic --model claude-haiku-5-5 \
  --key-env ANTHROPIC_API_KEY --price-in 1 --price-out 5 --spend --out runs.jsonl

python tools/chat-eval/chat_eval.py report runs.jsonl
```

`run` appends one JSON line a case and repeat (3 repeats by default; `--case <id>` for one case),
including the model's raw answer (first 4000 characters), so a failure can be read afterwards. `report` prints the summary
table and the per-case passes. Prices are passed in, not kept here, because they change.
`tests/test_chat_eval.py` checks the scoring with a faked model.

## The studio end to end (AI.2a)

`studio_check.py` drives the studio itself in Chromium against a real model: it opens the example song with
melody lock on, asks for a faster tempo, flute, a rock beat, chords and a locked melody transpose through the
chat form, reads the project draft from IndexedDB before and after each, and checks each change is one edit
that one Undo takes back (and the locked transpose changes nothing). It exits 1 when a check fails.

```bash
# Against a running web server whose chat is set up (TANDEM_PROVIDER, TANDEM_MODEL, TANDEM_BASE_URL, TANDEM_API_KEY)
~/m5-heavy.sh studio python tools/chat-eval/studio_check.py --url http://127.0.0.1:8765 --shots shots/ --out check.json

# The Mac app's own server code (guarded_app, launch secret, AI settings saved as the AI panel saves them,
# the key read from the named variable and kept in memory, never the Keychain)
~/m5-heavy.sh studio python tools/chat-eval/studio_check.py --desktop --model Inkling-2-Mini-oQ4e-mtp \
  --base-url http://127.0.0.1:8000/v1 --key-env OMLX_API_KEY --shots shots/ --out check.json
```
