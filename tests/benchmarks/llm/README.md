# Scenario B: small local models

A micro-benchmark for memory QA with a small local model. The model is reached through an OpenAI-compatible endpoint (Ollama on `http://127.0.0.1:11434/v1` by default). Example model names: `qwen2.5:3b`, `qwen2.5:7b`, `llama3.2:3b`, `phi3`.

Scenario A (`../`) measures retrieval only. This scenario asks the model to answer.

## What is measured

Each question has a difficulty (`easy`, `medium`, `hard`) and a type:

| Type | Retrieval | What a correct answer uses |
| --- | --- | --- |
| `single_fact` | required | One current fact |
| `updated_fact` | required | The current fact, not the outdated one |
| `contradiction` | required | Both live facts that conflict |
| `multi_hop` | required | Two linked facts |
| `temporal` | required | The fact that was true at the asked time |
| `abstention` | not required | A refusal: the answer is not in memory |

Abstention questions have no gold fact. The other types do. Distractor facts are in the corpus and are never gold.

Scores, reported per mode, per type, and per difficulty:

- Normalized match against the gold answers (case, punctuation, and extra words ignored). A contradiction also matches when every required mention is present.
- Abstention accuracy on abstention questions, and the false-abstention rate on the others.
- Stale-fact error rate: the answer names an outdated value and misses the gold value. Questions without a stale value are left out of this rate.
- Recall@k of gold fact ids, where the mode retrieves and the question has gold facts. No-memory and abstention do not contribute a recall.
- Latency (retrieval plus the chat call) and prompt/completion token counts. Missing usage fields are an estimate of about 4 characters per token, labeled `estimate` in the JSON.

`--judge` adds an optional local judge (same endpoint, `--judge-model`, defaulting to the answer model). The judge is off unless you set the flag. Core scores do not depend on it.

Output: `out/report.json` and `out/report.md`.

## Modes

- `none`: empty memory context. The model only sees the question.
- `rag`: plain vector retrieval. Every fact is embedded with a seeded hashing vector and ranked by cosine similarity. Outdated facts stay in the index.
- `graph`: Graph Memory MCP. Facts are written with `create_node` (`check_duplicates` off, so an update is not dropped as a paraphrase), outdated facts are `mark_outdated`, and links are `FOLLOWS_FROM` or `CONTRADICTS`. Search uses the server default, so outdated facts are hidden unless you pass `--include-outdated`.
- `mem0`, `graphiti` (alias `zep`), `letta`, `cognee`: same interface (`reset`, `ingest`, `search`). A mode is skipped, not scored as zero, when its library is not installed. Graphiti also needs `GRAPHITI_NEO4J_URI`. Letta needs `LETTA_BASE_URL`. Cognee needs `COGNEE_LOCAL=1`.

## Fairness

- One dataset, one system prompt, one user prompt, temperature 0, seed `1729` (also sent on the chat request).
- The answer model and the retrieved-text format are the same for every mode. Modes differ only in what `search` returns.
- Ingest order is dataset order. Top-k defaults to 4.
- RAG does not drop outdated facts. Graph Memory does, unless `--include-outdated` is set. That difference is part of the comparison: it should lower stale-fact errors and can miss a temporal question whose gold fact is outdated.
- Optional libraries are not given a zero when they are absent.
- No server code is changed by this harness.

## Dataset

`dataset.json` is the open corpus: short conversations (`episodes`) and the facts taken from them. Adapters ingest the fact records so gold ids stay stable. Episodes are the dialogue those facts came from.

Updates: coffee machine (Breville, then Moccamaster), spare key (red drawer, then blue locker), Nora's shift (morning, then evening). The lathe oil notes (SAE 30 and SAE 10W) both stay active. Multi-hop: evening supervisor to Priya's desk, and Project Lark to the north wall. Distractors: parking, lunch, radio.

## Run locally

From the repository root, with the answer model already available on the endpoint:

```bash
uv run python tests/benchmarks/llm/run.py --modes none,rag --model qwen2.5:3b
```

Graph Memory needs the same database the server uses (see the root README). The run writes into owner `llmbench` and deletes that graph first.

```bash
uv run python tests/benchmarks/llm/run.py --modes none,rag,graph --model llama3.2:3b
```

Other flags: `--base-url`, `--api-key`, `--k`, `--judge`, `--judge-model`, `--include-outdated`, `--limit`, `--out-dir`.

Unit tests for loading and scoring do not call a model:

```bash
uv run pytest -q tests/test_llm_benchmark.py
```
