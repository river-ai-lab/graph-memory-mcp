# Benchmark Suite

Implements Scenario A (synthetic architecture-decisions corpus) and fairness cases from `docs/benchmarks.md`.

Scenario B, a small local-model QA harness (no memory, plain RAG, Graph Memory), is in [`llm/README.md`](llm/README.md).

## What is measured

**Metrics (no LLM judge)**:
- **Recall@k**: Fraction of expected facts retrieved in top-k results
- **Stale rate**: Fraction of results that are outdated facts (should be excluded)
- **Contradiction detection**: Whether `CONTRADICTS` edges are surfaced
- **Duplicates refused**: Count of near-duplicate writes rejected at insert
- **Tokens in context**: Token count for compact recall queries
- **Multi-hop recall**: Fraction of multi-hop queries where all linked facts are retrieved

## Files

- `corpus.yaml`: 40 synthetic architecture decisions (superseded chains, contradictions, near-duplicates, multi-hop dependencies)
- `queries.yaml`: 20 queries covering current facts, outdated exclusion, contradictions, multi-hop, dedup, token budget, fairness cases
- `run_graph.py`: Seeds corpus and runs queries via Graph Memory MCP Python API
- `run_files.py`: File-based baselines (grep, BM25, full-context)
- `results_graph.json`: Graph Memory results (if run)
- `results_files.json`: Baseline results

## How to run

### Prerequisites

1. **Backend running** (for graph benchmark; requires ArcadeDB by default via env.example, or FalkorDB):
   ```bash
   docker compose up -d
   ```

2. **Environment configured**:
   ```bash
   cp env.example .env
   # Edit .env if needed (default password: falkordb123)
   ```

3. **Dependencies** (optional for BM25 baseline):
   ```bash
   pip install rank-bm25
   # or with uv: uv pip install rank-bm25
   # or run directly: uv run --with rank_bm25 python tests/benchmarks/run_files.py
   ```

### Run baselines (no database needed)

```bash
uv run --with rank_bm25 --with tiktoken python tests/benchmarks/run_files.py
```

This writes corpus as Markdown ADR files and runs:
- **Grep**: Case-insensitive substring search
- **BM25**: Lexical retrieval (requires `rank-bm25`)
- **Full-context**: Token count for all active facts

Results: `results_files.json`

### Run graph memory benchmark (requires backend)

```bash
uv run python tests/benchmarks/run_graph.py
```

This seeds an isolated `benchmark_{id}` owner and runs queries with:
- `search(..., compact=true)` for token-budgeted queries
- `search(..., include_outdated=false)` for current facts
- Contradiction pairs detection
- Duplicate rejection at write time

Results: `results_graph.json`

## Expected results (example, not guaranteed)

**Graph Memory strengths**:
- Recall@k: High on current facts after superseded decisions
- Stale rate: Low (outdated facts excluded by default)
- Duplicates refused: 4 near-paraphrases rejected at write
- Contradictions: Surfaced in `contradiction_pairs`
- Compact recall: Stays under 800-token budget

**File baselines strengths**:
- Grep: Wins on exact identifiers (e.g. `REDACTED_prod_key_12345`)
- Full-context: Wins on tiny corpus (39 facts, ~400 tokens total)
- BM25: Wins on keyword-heavy queries

## Caveats

- **Not end-to-end QA**: Scenario A measures retrieval, not answer correctness with an LLM. Scenario B (`llm/`) is the labeled QA run.
- **Synthetic corpus**: Real production memory has different characteristics.
- **No production concerns**: Does not measure latency, throughput, permissions, deletion, cost, or crash recovery.
- **Small corpus**: 39 facts is tiny. Full-context baseline is competitive at this size.

## Reproducing

1. Install dependencies: `uv sync` (installs dev group including PyYAML)
2. Start FalkorDB: `docker compose up -d`
3. Run: `python run_files.py && python run_graph.py`
4. Compare: `cat results_*.json`

## Adding queries

Edit `queries.yaml` to add test cases. Each query needs:
- `id`: Unique identifier
- `category`: `current_fact`, `contradiction`, `multihop`, `compact`, `fairness_grep`, etc.
- `text`: Query text
- `expect_keys`: List of fact keys that should be retrieved
- `forbid_keys`: List of fact keys that should NOT be retrieved (e.g. outdated)

## Limitations

This benchmark does NOT measure:
- Production reliability (crash recovery, concurrent writes)
- Latency or throughput
- Storage costs or embedding API costs
- Scalability (1M+ facts, 100+ owners)
- End-to-end QA accuracy (retrieval + LLM answering)

For those, use integration tests, load tests, and real-world deployments.
