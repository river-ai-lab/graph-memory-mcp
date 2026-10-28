# Benchmarks

This document outlines benchmarks for Graph Memory MCP, designed to show genuine strengths (write-time deduplication, explicit contradiction tracking, compact recall, physical isolation) while staying honest and reproducible. The file baselines run today and their results are published; the graph run is pending.

## Design principles

1. **Honest about what we test**: Retrieval recall, deduplication effectiveness, contradiction detection, and multi-hop graph traversal. We do not test end-to-end QA accuracy without clearly separating retrieval from answering.

2. **Reproducible**: Public dataset, public queries, deterministic metrics where possible. No LLM-as-judge for core metrics (use it only for optional end-to-end QA evaluation, clearly labeled).

3. **Show where we win**: Write-time dedup (how many near-duplicates are refused?), contradiction detection (are `CONTRADICTS` edges surfaced?), compact recall (do we stay under token budget?), multi-hop traversal (can the agent reach the answer in 2-3 hops?).

4. **Show where we lose**: Exact identifier search (grep wins), tiny corpora (full-context wins), automatic extraction (we do not do it).

5. **Compare against baselines we can run**, not self-reported numbers from other systems. Baselines: grep, BM25 top-k, whole-folder-in-context, and optionally Mem0 OSS (if we can run it) or @modelcontextprotocol/server-memory.

## Scenario A: Synthetic architecture-decisions corpus

**Purpose**: Measure retrieval recall, deduplication, contradiction detection, and multi-hop graph traversal on a realistic agent memory corpus.

### Corpus design

A synthetic corpus of 39 architecture decisions for a fictional project, stored as facts in the graph. The corpus includes:

- **Superseded decisions**: Decision A was valid on date X, superseded by decision B on date Y. Both facts are stored initially; the test measures whether `mark_outdated` removes A from results.
- **Contradictions**: Fact C says "use PostgreSQL for caching", fact D says "use Redis for caching", with no temporal ordering. A `CONTRADICTS` edge should exist or be created. The test measures whether it is surfaced in search results.
- **Near-duplicates**: Paraphrases of the same fact (e.g. "The API uses REST" vs "We chose REST for the API" vs "API design: RESTful"). Write-time deduplication should refuse 2 of these 3.
- **Multi-hop dependencies**: Fact E (`FOLLOWS_FROM` F, which `FOLLOWS_FROM` G). Queries that need E should reach it via graph traversal from F or G.
- **Noise and unrelated facts**: Filler facts on unrelated topics to increase corpus size and test ranking.

### Queries

~20 queries with expected fact IDs, covering:

1. **Current fact recall** (single-hop): "What caching system do we use?" → expects the non-outdated fact
2. **Outdated fact exclusion**: "What caching system do we use?" should NOT return the outdated fact (if `mark_outdated` was called)
3. **Contradiction detection**: "What caching system do we use?" should surface the `CONTRADICTS` edge in `contradiction_pairs` (if it exists)
4. **Multi-hop traversal**: "Why did we choose REST?" → expects facts E, F, G (linked via `FOLLOWS_FROM`)
5. **Near-duplicate deduplication**: Attempt to write 3 paraphrases of the same fact; measure how many are refused
6. **Compact recall**: "Summarize the API design decisions" with `compact=true` → measure whether result stays under `COMPACT_RECALL_TOKEN_BUDGET` (default 800 tokens)

### Metrics

- **Current-correct@k**: Top-k results contain the current (non-outdated) fact for the query. Measured at k=1, k=5, k=10.
- **Stale rate**: Fraction of results that are `status=outdated` (lower is better).
- **Contradiction surfacing**: Fraction of queries where contradictions exist and are listed in `contradiction_pairs` (higher is better).
- **Dedup effectiveness**: Fraction of near-duplicate writes refused by `memory_duplicate` (higher is better; target ~66% for 3-way paraphrases at threshold 0.92).
- **Multi-hop recall@k**: Fraction of multi-hop queries where all required facts (across 2-3 hops) are retrieved in top-k (measured at k=10, k=20).
- **Tokens in context**: Total tokens in the compact recall result (should be ≤ budget).
- **Retrieval calls**: Number of MCP tool calls to answer the query (compact recall should be 1-2; multi-hop walk might be 2-3).

### Baselines

1. **grep**: Keyword search over a directory of Markdown files (one file per fact). Measures exact match recall. Expected to win on exact identifiers, lose on semantic paraphrases.

2. **BM25 top-k**: Lexical retrieval over the corpus. No deduplication, no outdated marking, no contradiction detection. Expected to win on keyword-heavy queries, lose on multi-hop.

3. **Full-context**: All facts in the context window at once (simulates a small corpus where you just paste everything). Expected to win on tiny corpora (39 facts), lose on token budget (no compaction).

4. **@modelcontextprotocol/server-memory** (optional): Official MCP reference server. No deduplication, no versioning, no TTL. Expected to be comparable on basic retrieval, lose on dedup and outdated marking.

### Dataset format

```yaml
facts:
  - id: fact_001
    text: "The API uses REST for external integrations."
    status: active
    metadata:
      project: fictional_project
      created_by: architect
      decision_date: "2026-01-15"
  - id: fact_002
    text: "We decided to use REST for the public API."
    status: duplicate_refused  # Near-duplicate of fact_001
  - id: fact_003
    text: "Use PostgreSQL for caching to simplify the stack."
    status: outdated
    outdated_reason: "Superseded by fact_004"
  - id: fact_004
    text: "Use Redis for caching (decision 2026-03-10)."
    status: active
    contradicts: [fact_003]

queries:
  - id: query_01
    text: "What caching system do we use?"
    expected_ids: [fact_004]
    excluded_ids: [fact_003]
    expect_contradictions: true
  - id: query_02
    text: "Why did we choose REST for the API?"
    expected_ids: [fact_001, fact_005, fact_006]  # Multi-hop via FOLLOWS_FROM
    max_hops: 2
```

## Scenario B: LongMemEval-S retrieval (optional)

**Purpose**: Measure retrieval recall on an external public benchmark for comparison with other systems.

### Dataset

LongMemEval-S (500 questions, ~115k tokens, multi-session history). Source: [GitHub repository](https://github.com/xiaowu0162/LongMemEval).

### Scope

**Retrieval recall only** (not end-to-end QA accuracy). Ingest the conversation history as facts, run the 500 queries, measure R@5 and R@10 (fraction of queries where at least one gold-standard evidence session is retrieved in top-k).

### Important caveats

1. **Not an end-to-end QA benchmark**: We measure retrieval, not answer correctness. LongMemEval is designed for QA; we use only the retrieval component.

2. **No automatic extraction**: Graph Memory MCP requires explicit fact writes. The adapter must parse the history and write facts with `create_node`. This preprocessing step is part of the measurement (and a weakness compared to systems with automatic extraction).

3. **Label as retrieval R@k**: Results are "Retrieval R@5" and "Retrieval R@10", not "LongMemEval accuracy" or "LongMemEval score". Do not claim better QA performance than systems that report end-to-end accuracy.

4. **Dataset revision and settings matter**: Record the exact LongMemEval revision, tokenizer, retrieval settings (pre-filter vs post-filter, similarity threshold), and whether the oracle or full history is used. Results are not comparable across different settings.

### Metrics

- **Retrieval R@5**: Fraction of queries where at least one gold evidence session is in top-5 retrieved facts.
- **Retrieval R@10**: Same, top-10.

### Comparison

Compare against:

1. **BM25 baseline** (from the LongMemEval repository, if available)
2. **Full-context baseline** (no retrieval; entire history in context)
3. **Optional**: Mem0 OSS adapter (if we can run it on the same dataset)

Do NOT compare against published scores from Supermemory, rohitg00/agentmemory, or Mastra unless we reproduce their exact setup (dataset revision, judge, answering model). Their scores are end-to-end QA, not retrieval-only.

## Scenario C: Fairness cases (where baselines win)

**Purpose**: Honestly document cases where Graph Memory MCP loses to simpler baselines.

### Case 1: Exact identifier search

**Setup**: Corpus with facts containing exact identifiers (UUIDs, API keys redacted as `REDACTED_123`, file paths). Query: "Find REDACTED_123".

**Expected result**: grep wins (100% recall), vector search loses (identifiers do not embed well). BM25 wins (exact token match).

**Measurement**: Recall@1 for exact identifier queries. Report grep and BM25 as the winners.

### Case 2: Tiny corpus (≤10 facts)

**Setup**: Corpus with 10 facts. Query: any factual question.

**Expected result**: Full-context wins (just paste all 10 facts; no retrieval needed). Graph Memory MCP and other retrieval systems add latency and complexity for no benefit.

**Measurement**: Answer correctness (or retrieval recall) for tiny corpora. Report full-context as the winner.

### Case 3: Automatic extraction needed

**Setup**: Raw conversation transcript. No agent explicitly writes facts.

**Expected result**: Mem0 and Graphiti win (they extract facts automatically). Graph Memory MCP requires manual `create_node` calls or preprocessing with `ingest_knowledge`.

**Measurement**: Setup complexity (lines of adapter code needed to ingest the transcript). Report Mem0 and Graphiti as easier for this use case.

## Tool-to-metric mapping

Each query category maps to actual Graph Memory MCP tools and parameters:

| Query category | Tool(s) used | Parameters |
|----------------|--------------|------------|
| Current fact recall | `search` | `query`, `include_outdated=false` (default) |
| Outdated fact exclusion | `search` | `include_outdated=false`; measure stale rate |
| Contradiction detection | `search` | Check `contradiction_pairs` in result |
| Multi-hop traversal | `search` → `get_context` | `depth=2`, follow `FOLLOWS_FROM` edges |
| Near-duplicate dedup | `create_node` | Expect `memory_duplicate` error at threshold 0.92 |
| Compact recall | `search` | `compact=true`, measure tokens ≤ `COMPACT_RECALL_TOKEN_BUDGET` |
| Retrieval R@k (LongMemEval) | `search` | `limit=k`, measure recall of gold evidence |

## Implementation skeleton (optional)

A minimal runnable benchmark under `bench/` (only if it actually runs; otherwise just this plan document).

### File structure

```
bench/
  corpus_architecture_decisions.yaml   # Scenario A corpus
  queries_architecture_decisions.yaml  # Scenario A queries
  run_scenario_a.py                    # Loads corpus, runs queries, computes metrics
  adapters/
    graph_memory_mcp.py                # Adapter for Graph Memory MCP
    grep_baseline.py                   # Adapter for grep
    bm25_baseline.py                   # Adapter for BM25
  README.md                            # How to run
```

### Example adapter interface

```python
class MemoryAdapter:
    def ingest(self, facts: List[Fact]) -> None:
        """Write facts to the memory system."""
        pass

    def query(self, query_text: str, k: int = 10) -> List[str]:
        """Retrieve top-k fact IDs for the query."""
        pass

    def mark_outdated(self, fact_id: str, reason: str = "") -> None:
        """Mark a fact as outdated (if supported)."""
        pass

    def create_contradiction(self, fact_id_a: str, fact_id_b: str) -> None:
        """Create a CONTRADICTS edge (if supported)."""
        pass
```

### Example run

```bash
# From repository root:
uv run --with rank_bm25 python tests/benchmarks/run_files.py
uv run python tests/benchmarks/run_graph.py
```

Output: Markdown table with metrics per adapter, plus a narrative summary of where each system wins and loses.

## Scenario B: small local models

Scenario A stops at retrieval. Scenario B is a separate micro-benchmark that asks a small local model (Ollama or any OpenAI-compatible endpoint) to answer from memory. Dataset, runner, scoring, and the comparison adapters live in `tests/benchmarks/llm/`. How to run it, and what is measured, is in `tests/benchmarks/llm/README.md`.

Modes are no memory, plain vector RAG, and Graph Memory MCP, on one shared dataset and one shared prompt. Question types that need retrieval are marked in the dataset; abstention does not. The judge is optional and off unless you pass `--judge`. Scenario A numbers are unchanged.

## What this benchmark does NOT measure

1. **Production reliability**: Permissions, deletion, crash recovery, concurrent writes, backup/restore.
2. **Latency and throughput**: Query latency, writes per second, index build time.
3. **Cost**: Embedding API costs, storage costs, LLM extraction costs (where applicable).
4. **Scalability**: Performance on 1M+ facts, 100+ owners, large graphs.
5. **End-to-end QA accuracy**: Scenario A does not score an LLM answer. Scenario B does, and it labels that split (match, abstention, stale-fact errors, recall@k, latency, tokens).

These are important for production deployments but are out of scope for this benchmark plan. Measure them separately with integration tests, load tests, and cost analysis.

## When to run this benchmark

- **Before major releases** to ensure no regression on retrieval recall or deduplication effectiveness.
- **When comparing against a new competitor** (reproduce their setup and ours side-by-side).
- **When performance claims are made** (back them up with reproducible numbers).

Do not use benchmark results alone as proof of production readiness. Use them as one data point among integration tests, load tests, and real-world deployments.

## Contributing benchmarks

If you run these benchmarks or extend them:

1. **Document your setup**: Dataset revision, corpus size, query set, retrieval settings, hardware, software versions.
2. **Share reproducers**: Scripts, corpus files (if permissible), and adapter code.
3. **Report honestly**: Include cases where Graph Memory MCP loses. Do not cherry-pick only the winning metrics.
4. **Cite sources**: If using external datasets (LongMemEval, etc.), cite the original paper and repository with access date.

Open a pull request with your results in `bench/results/YYYY-MM-DD-scenario-name.md`.

## References

- LongMemEval: [GitHub repository](https://github.com/xiaowu0162/LongMemEval), [ICLR 2025 paper](https://arxiv.org/abs/2410.10813)
- BM25: [Wikipedia](https://en.wikipedia.org/wiki/Okapi_BM25)
- Retrieval benchmarks in the memory space: Supermemory's [LongMemEval-S report](https://supermemory.ai/research/longmembench/), Mastra's [Observational Memory report](https://mastra.ai/research/observational-memory)
- Fairness in benchmarking: [Mem0's benchmark philosophy](https://docs.mem0.ai/) (no direct link; general principle of comparing like-for-like)
