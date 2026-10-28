#!/usr/bin/env python3
"""Render results_structural.json as markdown tables."""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent


def main() -> None:
    src = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else HERE.parent / "results_structural.json"
    )
    res = json.loads(src.read_text())
    out = [
        "# Structural retrieval benchmark",
        "",
        f"Tokenizer: `{res['tokenizer']}`. Metric: all gold facts of a question inside the first N context tokens (all@N); recall@N is the per-fact fraction.",
        "",
    ]
    for lvl, L in res["levels"].items():
        out += [
            f"## Noise {lvl}",
            "",
            "| system | type | n | recall@200 | recall@500 | recall@1000 | all@1000 | median tokens to all gold | stale@1000 | latency ms |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for sysname, S in L["systems"].items():
            for typ, a in S["by_type"].items():
                out.append(
                    f"| {sysname} | {typ} | {a['n']} | {a.get('recall@200')} | {a.get('recall@500')} | "
                    f"{a.get('recall@1000')} | {a.get('all@1000')} | {a['median_tokens_all_gold']} ({a['all_gold_found']}) | "
                    f"{a.get('stale@1000', '')} | {a['latency_ms_median']} |"
                )
        out.append("")
    print("\n".join(out))


if __name__ == "__main__":
    main()
