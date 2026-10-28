#!/usr/bin/env python3
"""Run the local-model memory benchmark.

Example:
  uv run python tests/benchmarks/llm/run.py --modes none,rag
  uv run python tests/benchmarks/llm/run.py --modes graph --model qwen2.5:3b
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from benchlib.dataset import load_dataset  # noqa: E402
from benchlib.llm import DEFAULT_BASE_URL, DEFAULT_MODEL, ChatClient  # noqa: E402
from benchlib.report import dump_json, render_markdown  # noqa: E402
from benchlib.runner import build_report, run_mode  # noqa: E402

MODES = ("none", "rag", "graph", "mem0", "graphiti", "zep", "letta", "cognee")


def _parse_modes(value: str) -> list[str]:
    modes = [item.strip() for item in value.split(",") if item.strip()]
    unknown = [item for item in modes if item not in MODES]
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown modes: {', '.join(unknown)}")
    if not modes:
        raise argparse.ArgumentTypeError("at least one mode is required")
    return modes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scenario B local-model memory benchmark"
    )
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--modes", type=_parse_modes, default=["none", "rag", "graph"])
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default="ollama")
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--k", type=int, default=4)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--include-outdated", action="store_true")
    parser.add_argument("--owner-id", default="llmbench")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_ROOT / "out",
    )
    args = parser.parse_args(argv)

    dataset = load_dataset(args.dataset)
    if args.seed is not None and args.seed != dataset.seed:
        print(
            f"warning: --seed {args.seed} does not change the dataset seed {dataset.seed}; "
            "the chat client uses the dataset seed",
            file=sys.stderr,
        )
    seed = dataset.seed
    client = ChatClient(
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        seed=seed,
        timeout_s=args.timeout,
    )
    judge = None
    judge_model = None
    if args.judge:
        judge_model = args.judge_model or args.model
        judge = ChatClient(
            base_url=args.base_url,
            model=judge_model,
            api_key=args.api_key,
            seed=seed,
            timeout_s=args.timeout,
        )
    modes = {}
    exit_code = 0
    try:
        for name in args.modes:
            print(f"running {name}...")
            payload = run_mode(
                name,
                dataset,
                client,
                k=args.k,
                include_outdated=args.include_outdated,
                judge=judge,
                limit=args.limit,
                owner_id=args.owner_id,
            )
            modes[name] = payload
            if payload.get("skipped"):
                print(f"  skipped: {payload['reason']}")
            elif payload.get("error"):
                print(f"  error: {payload['error']}", file=sys.stderr)
                exit_code = 2
            else:
                match = payload["summary"]["overall"]["match_rate"]
                print(f"  match_rate={match}")
    finally:
        client.close()
        if judge is not None:
            judge.close()

    report = build_report(
        dataset,
        modes,
        model=args.model,
        judge_model=judge_model,
        k=args.k,
        include_outdated=args.include_outdated,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "report.json"
    md_path = args.out_dir / "report.md"
    json_path.write_text(dump_json(report), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
