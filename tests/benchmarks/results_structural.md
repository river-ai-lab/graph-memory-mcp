# Structural retrieval benchmark (Scenario 1)

Run: `GRAPH_BACKEND=falkordb python tests/benchmarks/structural/run.py`, then `report.py`. Opt-in test: `STRUCTURAL_BENCH=1 pytest -m structural_bench`. FalkorDB.

Tokenizer: `regex \w+|[^\w\s]`. Metric: all gold facts of a question inside the first N context tokens (all@N); recall@N is the per-fact fraction.

## Noise 0

| system | type | n | recall@200 | recall@500 | recall@1000 | all@1000 | median tokens to all gold | stale@1000 | latency ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rag | aggregate | 8 | 1.0 | 1.0 | 1.0 | 1.0 | 29.0 (8/8) |  | 9.9 |
| rag | chain2 | 8 | 0.812 | 1.0 | 1.0 | 1.0 | 121.5 (8/8) |  | 10.2 |
| rag | chain3 | 8 | 0.833 | 1.0 | 1.0 | 1.0 | 210.5 (8/8) |  | 11.5 |
| rag | control | 10 | 1.0 | 1.0 | 1.0 | 1.0 | 7.0 (10/10) |  | 14.5 |
| rag | current | 6 | 1.0 | 1.0 | 1.0 | 1.0 | 12.5 (6/6) | 1.0 | 15.0 |
| rag | all | 40 | 0.929 | 1.0 | 1.0 | 1.0 | 29.0 (40/40) | 1.0 | 12.1 |
| graph_search | aggregate | 8 | 1.0 | 1.0 | 1.0 | 1.0 | 29.0 (8/8) |  | 25.8 |
| graph_search | chain2 | 8 | 0.812 | 1.0 | 1.0 | 1.0 | 121.5 (8/8) |  | 26.2 |
| graph_search | chain3 | 8 | 0.833 | 1.0 | 1.0 | 1.0 | 210.5 (8/8) |  | 29.7 |
| graph_search | control | 10 | 1.0 | 1.0 | 1.0 | 1.0 | 7.0 (10/10) |  | 24.8 |
| graph_search | current | 6 | 1.0 | 1.0 | 1.0 | 1.0 | 6.0 (6/6) | 0.0 | 25.5 |
| graph_search | all | 40 | 0.929 | 1.0 | 1.0 | 1.0 | 29.0 (40/40) | 0.0 | 26.2 |
| graph_recall_d2 | aggregate | 8 | 1.0 | 1.0 | 1.0 | 1.0 | 31.0 (8/8) |  | 14.0 |
| graph_recall_d2 | chain2 | 8 | 1.0 | 1.0 | 1.0 | 1.0 | 106.5 (8/8) |  | 15.4 |
| graph_recall_d2 | chain3 | 8 | 0.667 | 0.667 | 0.667 | 0.125 | 195 (1/8) |  | 19.2 |
| graph_recall_d2 | control | 10 | 1.0 | 1.0 | 1.0 | 1.0 | 7.0 (10/10) |  | 14.1 |
| graph_recall_d2 | current | 6 | 1.0 | 1.0 | 1.0 | 1.0 | 6.0 (6/6) | 0.0 | 16.0 |
| graph_recall_d2 | all | 40 | 0.933 | 0.933 | 0.933 | 0.825 | 18 (33/40) | 0.0 | 14.9 |
| graph_recall_d3 | aggregate | 8 | 1.0 | 1.0 | 1.0 | 1.0 | 33.0 (8/8) |  | 18.5 |
| graph_recall_d3 | chain2 | 8 | 1.0 | 1.0 | 1.0 | 1.0 | 106.5 (8/8) |  | 19.1 |
| graph_recall_d3 | chain3 | 8 | 0.708 | 0.708 | 0.708 | 0.25 | 167.0 (2/8) |  | 16.2 |
| graph_recall_d3 | control | 10 | 1.0 | 1.0 | 1.0 | 1.0 | 7.0 (10/10) |  | 14.9 |
| graph_recall_d3 | current | 6 | 1.0 | 1.0 | 1.0 | 1.0 | 6.5 (6/6) | 0.0 | 17.1 |
| graph_recall_d3 | all | 40 | 0.942 | 0.942 | 0.942 | 0.85 | 21.5 (34/40) | 0.0 | 16.9 |

## Noise 1000

| system | type | n | recall@200 | recall@500 | recall@1000 | all@1000 | median tokens to all gold | stale@1000 | latency ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rag | aggregate | 8 | 1.0 | 1.0 | 1.0 | 1.0 | 29.0 (8/8) |  | 65.1 |
| rag | chain2 | 8 | 0.5 | 0.562 | 0.75 | 0.5 | 624.0 (4/8) |  | 65.1 |
| rag | chain3 | 8 | 0.333 | 0.458 | 0.583 | 0.125 | 266 (1/8) |  | 59.8 |
| rag | control | 10 | 1.0 | 1.0 | 1.0 | 1.0 | 7.0 (10/10) |  | 32.3 |
| rag | current | 6 | 1.0 | 1.0 | 1.0 | 1.0 | 12.5 (6/6) | 1.0 | 57.8 |
| rag | all | 40 | 0.767 | 0.804 | 0.867 | 0.725 | 18 (29/40) | 1.0 | 59.7 |
| graph_search | aggregate | 8 | 1.0 | 1.0 | 1.0 | 1.0 | 29.0 (8/8) |  | 39.8 |
| graph_search | chain2 | 8 | 0.5 | 0.562 | 0.75 | 0.5 | 624.0 (4/8) |  | 37.9 |
| graph_search | chain3 | 8 | 0.333 | 0.458 | 0.583 | 0.125 | 266 (1/8) |  | 41.4 |
| graph_search | control | 10 | 1.0 | 1.0 | 1.0 | 1.0 | 7.0 (10/10) |  | 36.7 |
| graph_search | current | 6 | 1.0 | 1.0 | 1.0 | 1.0 | 6.0 (6/6) | 0.0 | 36.3 |
| graph_search | all | 40 | 0.767 | 0.804 | 0.867 | 0.725 | 7 (29/40) | 0.0 | 38.2 |
| graph_recall_d2 | aggregate | 8 | 1.0 | 1.0 | 1.0 | 1.0 | 33.0 (8/8) |  | 58.5 |
| graph_recall_d2 | chain2 | 8 | 1.0 | 1.0 | 1.0 | 1.0 | 122.5 (8/8) |  | 64.1 |
| graph_recall_d2 | chain3 | 8 | 0.667 | 0.667 | 0.667 | 0.0 | None (0/8) |  | 63.4 |
| graph_recall_d2 | control | 10 | 1.0 | 1.0 | 1.0 | 1.0 | 7.0 (10/10) |  | 62.3 |
| graph_recall_d2 | current | 6 | 1.0 | 1.0 | 1.0 | 1.0 | 7.0 (6/6) | 0.0 | 64.2 |
| graph_recall_d2 | all | 40 | 0.933 | 0.933 | 0.933 | 0.8 | 14.0 (32/40) | 0.0 | 62.8 |
| graph_recall_d3 | aggregate | 8 | 1.0 | 1.0 | 1.0 | 1.0 | 33.0 (8/8) |  | 78.6 |
| graph_recall_d3 | chain2 | 8 | 1.0 | 1.0 | 1.0 | 1.0 | 123.5 (8/8) |  | 79.7 |
| graph_recall_d3 | chain3 | 8 | 0.667 | 0.667 | 0.667 | 0.0 | None (0/8) |  | 75.6 |
| graph_recall_d3 | control | 10 | 1.0 | 1.0 | 1.0 | 1.0 | 7.0 (10/10) |  | 78.4 |
| graph_recall_d3 | current | 6 | 1.0 | 1.0 | 1.0 | 1.0 | 7.0 (6/6) | 0.0 | 78.2 |
| graph_recall_d3 | all | 40 | 0.933 | 0.933 | 0.933 | 0.8 | 14.0 (32/40) | 0.0 | 78.0 |

## Noise 10000

| system | type | n | recall@200 | recall@500 | recall@1000 | all@1000 | median tokens to all gold | stale@1000 | latency ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rag | aggregate | 8 | 1.0 | 1.0 | 1.0 | 1.0 | 29.0 (8/8) |  | 76.0 |
| rag | chain2 | 8 | 0.5 | 0.5 | 0.5 | 0.0 | None (0/8) |  | 69.8 |
| rag | chain3 | 8 | 0.333 | 0.333 | 0.333 | 0.0 | None (0/8) |  | 56.2 |
| rag | control | 10 | 1.0 | 1.0 | 1.0 | 1.0 | 7.0 (10/10) |  | 77.6 |
| rag | current | 6 | 1.0 | 1.0 | 1.0 | 1.0 | 12.5 (6/6) | 1.0 | 107.8 |
| rag | all | 40 | 0.767 | 0.767 | 0.767 | 0.6 | 7.0 (24/40) | 1.0 | 75.1 |
| graph_search | aggregate | 8 | 1.0 | 1.0 | 1.0 | 1.0 | 29.0 (8/8) |  | 111.9 |
| graph_search | chain2 | 8 | 0.5 | 0.5 | 0.5 | 0.0 | None (0/8) |  | 105.1 |
| graph_search | chain3 | 8 | 0.333 | 0.333 | 0.333 | 0.0 | None (0/8) |  | 108.9 |
| graph_search | control | 10 | 1.0 | 1.0 | 1.0 | 1.0 | 7.0 (10/10) |  | 108.1 |
| graph_search | current | 6 | 1.0 | 1.0 | 1.0 | 1.0 | 6.0 (6/6) | 0.0 | 84.5 |
| graph_search | all | 40 | 0.767 | 0.767 | 0.767 | 0.6 | 7.0 (24/40) | 0.0 | 107.4 |
| graph_recall_d2 | aggregate | 8 | 1.0 | 1.0 | 1.0 | 1.0 | 33.0 (8/8) |  | 417.9 |
| graph_recall_d2 | chain2 | 8 | 0.938 | 0.938 | 0.938 | 0.875 | 137 (7/8) |  | 430.7 |
| graph_recall_d2 | chain3 | 8 | 0.583 | 0.583 | 0.583 | 0.0 | None (0/8) |  | 449.7 |
| graph_recall_d2 | control | 10 | 1.0 | 1.0 | 1.0 | 1.0 | 7.0 (10/10) |  | 401.4 |
| graph_recall_d2 | current | 6 | 1.0 | 1.0 | 1.0 | 1.0 | 7.0 (6/6) | 0.0 | 405.6 |
| graph_recall_d2 | all | 40 | 0.904 | 0.904 | 0.904 | 0.775 | 10 (31/40) | 0.0 | 416.8 |
| graph_recall_d3 | aggregate | 8 | 1.0 | 1.0 | 1.0 | 1.0 | 33.0 (8/8) |  | 502.0 |
| graph_recall_d3 | chain2 | 8 | 0.938 | 0.938 | 0.938 | 0.875 | 141 (7/8) |  | 498.8 |
| graph_recall_d3 | chain3 | 8 | 0.583 | 0.583 | 0.583 | 0.0 | None (0/8) |  | 379.6 |
| graph_recall_d3 | control | 10 | 1.0 | 1.0 | 1.0 | 1.0 | 7.0 (10/10) |  | 521.0 |
| graph_recall_d3 | current | 6 | 1.0 | 1.0 | 1.0 | 1.0 | 7.0 (6/6) | 0.0 | 514.3 |
| graph_recall_d3 | all | 40 | 0.904 | 0.904 | 0.904 | 0.775 | 10 (31/40) | 0.0 | 503.9 |

## Setup

Dataset: `structural/dataset.json` (core + questions) from `structural/generate.py` (seed 1729, no LLM); noise is rebuilt from the seed by `run.py`. 107 core facts, 56 entities, 242 edges (Fact-MENTIONS->Entity, typed Entity edges MEMBER_OF/LEADS/OPERATES/LOCATED_IN/OWNS, FOLLOWS_FROM on update chains; 12 facts marked outdated via `mark_outdated`). Noise: 10,000 facts with the same templates and disjoint entities, loaded nested (first 1k, then the rest). 40 questions: chain3 8, chain2 8, aggregate 8, current 6, control 10. In chain questions the final fact shares no content word with the question.

Systems: `rag` = cosine over all fact sentences with the server's ONNX embeddings (outdated included); `graph_search` = `search(node_types=["Fact"], limit=100)`; `graph_recall_dN` = `recall_context(depth=N, limit=5, max_nodes=50)`. Context is the returned list in order; tokens are summed in that order.

## Reading

- `graph_search` ranks the same as RAG on every chain question; it only drops outdated facts (stale@1000 0.0 vs 1.0).
- `recall_context` keeps 2-hop chains at 0.875–1.0 all@1000 under 10k noise where RAG/search fall to 0.0.
- 3-hop chains fail for every system. In `recall_context` the 5 seeds include noise facts with the same surname; the multi-source BFS spends the 50-node budget (the server cap `SUBGRAPH_MAX_NODES_LIMIT`) on hop 1–2 of all seeds before hop 3 of the right one. depth=3 does not help.
