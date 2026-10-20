#!/usr/bin/env python3
"""
Baseline benchmarks: file-based memory (grep, BM25, full-context).
Full-context returns all facts (simulates pasting entire corpus in context).
Writes corpus as Markdown ADR files and runs baselines without a graph database.
"""

import json
import tempfile
from pathlib import Path
from typing import Dict, List

import yaml

try:
    import tiktoken

    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False


def load_corpus(corpus_path: str) -> List[Dict]:
    """Load corpus from YAML."""
    with open(corpus_path) as f:
        data = yaml.safe_load(f)
    return [
        fact
        for fact in data["facts"]
        if fact.get("status") != "should_refuse"  # Skip test duplicates
    ]


def load_queries(queries_path: str) -> List[Dict]:
    """Load queries from YAML."""
    with open(queries_path) as f:
        data = yaml.safe_load(f)
    return data["queries"]


def write_corpus_as_files(corpus: List[Dict], output_dir: Path) -> Dict[str, str]:
    """Write corpus as Markdown ADR files. Returns key->filepath mapping."""
    output_dir.mkdir(parents=True, exist_ok=True)
    key_to_file = {}

    for fact in corpus:
        key = fact["key"]
        filename = f"adr-{key}.md"
        filepath = output_dir / filename

        content = f"# {key}\n\n"
        content += f"{fact['text']}\n\n"
        content += f"- Status: {fact.get('status', 'active')}\n"
        content += f"- Created: {fact.get('created_at', 'unknown')}\n"

        if fact.get("outdated_at"):
            content += f"- Outdated: {fact['outdated_at']}\n"
        if fact.get("supersedes"):
            content += f"- Supersedes: {fact['supersedes']}\n"
        if fact.get("follows_from"):
            content += f"- Follows from: {fact['follows_from']}\n"
        if fact.get("contradicts"):
            content += f"- Contradicts: {fact['contradicts']}\n"

        filepath.write_text(content)
        key_to_file[key] = str(filepath)

    return key_to_file


def run_grep_baseline(
    query_text: str, corpus_dir: Path, key_to_file: Dict[str, str]
) -> List[str]:
    """Grep baseline: case-insensitive substring search. Returns matching keys."""
    query_lower = query_text.lower()
    matching_keys = []

    for key, filepath in key_to_file.items():
        content = Path(filepath).read_text().lower()
        if query_lower in content or any(
            word in content for word in query_lower.split()
        ):
            matching_keys.append(key)

    return matching_keys[:10]  # Top-10


def run_bm25_baseline(
    query_text: str, corpus: List[Dict], top_k: int = 10
) -> List[str]:
    """BM25 baseline using rank_bm25. Returns top-k keys."""
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        print("rank_bm25 not installed, skipping BM25 baseline")
        return []

    # Tokenize corpus
    tokenized_corpus = []
    keys = []
    for fact in corpus:
        if fact.get("status") == "outdated":
            continue  # BM25 doesn't know about outdated
        text = fact["text"].lower()
        tokenized_corpus.append(text.split())
        keys.append(fact["key"])

    if not tokenized_corpus:
        return []

    bm25 = BM25Okapi(tokenized_corpus)
    query_tokens = query_text.lower().split()
    scores = bm25.get_scores(query_tokens)

    # Get top-k indices
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[
        :top_k
    ]
    return [keys[i] for i in top_indices]


def evaluate_query(
    query: Dict,
    result_keys: List[str],
    corpus: List[Dict],
    key_to_fact: Dict[str, Dict],
) -> Dict:
    """Evaluate query result against expectations."""
    expect_keys = set(query.get("expect_keys", []))
    forbid_keys = set(query.get("forbid_keys", []))
    result_set = set(result_keys)

    # Current-correct@k
    correct_in_result = expect_keys & result_set
    recall_at_k = len(correct_in_result) / len(expect_keys) if expect_keys else 0.0

    # Forbidden keys (stale) present
    stale_present = forbid_keys & result_set
    stale_rate = len(stale_present) / len(result_set) if result_set else 0.0

    return {
        "recall_at_k": recall_at_k,
        "stale_rate": stale_rate,
        "correct_count": len(correct_in_result),
        "expected_count": len(expect_keys),
        "stale_count": len(stale_present),
    }


def run_full_context(facts: List[Dict], queries: List[Dict]) -> List[Dict]:
    """
    Full-context baseline: all facts in context (active + outdated).
    Recall = 1.0 by construction; reports stale rate and token count.
    """
    results = []

    # Build full context text
    all_texts = [f["text"] for f in facts]
    context_text = "\n\n".join(all_texts)

    # Count tokens
    if HAS_TIKTOKEN:
        enc = tiktoken.get_encoding("cl100k_base")
        token_count = len(enc.encode(context_text))
    else:
        # Approximation: ~4 chars per token
        token_count = len(context_text) // 4

    for query in queries:
        expected = set(query.get("expect_keys", []))
        forbid_keys = set(query.get("forbid_keys", []))

        # Full context includes all facts
        result_keys = [f["key"] for f in facts]

        # Calculate metrics
        correct = expected & set(result_keys)
        stale = forbid_keys & set(result_keys)

        recall = len(correct) / len(expected) if expected else 0.0
        stale_rate = len(stale) / len(result_keys) if result_keys else 0.0

        results.append(
            {
                "query_id": query["id"],
                "category": query.get("category", ""),
                "result_keys": result_keys[:5],  # First 5 for brevity
                "metrics": {
                    "recall_at_k": recall,
                    "stale_rate": stale_rate,
                    "correct_count": len(correct),
                    "expected_count": len(expected),
                    "stale_count": len(stale),
                    "token_count": token_count,
                    "total_facts": len(result_keys),
                },
            }
        )

    return results


def main():
    """Run file-based baselines."""
    script_dir = Path(__file__).parent
    corpus_path = script_dir / "corpus.yaml"
    queries_path = script_dir / "queries.yaml"

    print("Loading corpus and queries...")
    corpus = load_corpus(corpus_path)
    queries = load_queries(queries_path)
    key_to_fact = {f["key"]: f for f in corpus}

    print(f"Loaded {len(corpus)} facts, {len(queries)} queries\n")

    # Write corpus as files
    with tempfile.TemporaryDirectory() as tmpdir:
        corpus_dir = Path(tmpdir) / "adr"
        print(f"Writing corpus to {corpus_dir}...")
        key_to_file = write_corpus_as_files(corpus, corpus_dir)

        results = {"grep": [], "bm25": [], "full_context": []}

        # Run baselines per query
        print("\n=== Running baselines ===")
        for query in queries:
            qid = query["id"]
            text = query["text"]
            category = query.get("category", "unknown")

            print(f"\n{qid} ({category}): {text}")

            # Grep baseline
            grep_keys = run_grep_baseline(text, corpus_dir, key_to_file)
            grep_metrics = evaluate_query(query, grep_keys, corpus, key_to_fact)
            results["grep"].append(
                {
                    "query_id": qid,
                    "category": category,
                    "result_keys": grep_keys[:5],
                    "metrics": grep_metrics,
                }
            )
            print(
                f"  Grep: recall@k={grep_metrics['recall_at_k']:.2f}, stale={grep_metrics['stale_rate']:.2f}"
            )

            # BM25 baseline
            bm25_keys = run_bm25_baseline(text, corpus, top_k=10)
            if bm25_keys:
                bm25_metrics = evaluate_query(query, bm25_keys, corpus, key_to_fact)
                results["bm25"].append(
                    {
                        "query_id": qid,
                        "category": category,
                        "result_keys": bm25_keys[:5],
                        "metrics": bm25_metrics,
                    }
                )
                print(
                    f"  BM25: recall@k={bm25_metrics['recall_at_k']:.2f}, stale={bm25_metrics['stale_rate']:.2f}"
                )

        # Run full-context baseline
        print("\nRunning full-context baseline...")
        results["full_context"] = run_full_context(corpus, queries)
        for r in results["full_context"][:3]:  # Show first 3
            m = r["metrics"]
            print(
                f"  {r['query_id']}: recall={m['recall_at_k']:.2f}, stale={m['stale_rate']:.2f}, tokens={m['token_count']}, total_facts={m['total_facts']}"
            )

        # Write results
        output_path = script_dir / "results_files.json"
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)

        print(f"\n\nResults written to {output_path}")

        # Summary statistics
        if results["grep"]:
            avg_grep_recall = sum(
                r["metrics"]["recall_at_k"] for r in results["grep"]
            ) / len(results["grep"])
            avg_grep_stale = sum(
                r["metrics"]["stale_rate"] for r in results["grep"]
            ) / len(results["grep"])
            print(
                f"\nGrep average: recall={avg_grep_recall:.2f}, stale={avg_grep_stale:.2f}"
            )

        if results["bm25"]:
            avg_bm25_recall = sum(
                r["metrics"]["recall_at_k"] for r in results["bm25"]
            ) / len(results["bm25"])
            avg_bm25_stale = sum(
                r["metrics"]["stale_rate"] for r in results["bm25"]
            ) / len(results["bm25"])
            print(
                f"BM25 average: recall={avg_bm25_recall:.2f}, stale={avg_bm25_stale:.2f}"
            )

        if results.get("full_context"):
            avg_fc_recall = sum(
                r["metrics"]["recall_at_k"] for r in results["full_context"]
            ) / len(results["full_context"])
            avg_fc_stale = sum(
                r["metrics"]["stale_rate"] for r in results["full_context"]
            ) / len(results["full_context"])
            avg_fc_tokens = sum(
                r["metrics"]["token_count"] for r in results["full_context"]
            ) / len(results["full_context"])
            print(
                f"Full-context average: recall={avg_fc_recall:.2f}, stale={avg_fc_stale:.2f}, tokens={int(avg_fc_tokens)}"
            )


if __name__ == "__main__":
    main()
