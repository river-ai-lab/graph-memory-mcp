"""JSON and Markdown reports."""

from __future__ import annotations

import json
from typing import Any


def _fmt(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _table(headers: list[str], rows: list[list[object]]) -> str:
    head = "| " + " | ".join(headers) + " |"
    rule = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(_fmt(cell) for cell in row) + " |" for row in rows]
    return "\n".join([head, rule, *body])


def _summary_row(mode: str, split: str, summary: dict[str, Any]) -> list[object]:
    return [
        mode,
        split,
        summary["n"],
        summary["match_rate"],
        summary["abstention_accuracy"],
        summary["stale_error_rate"],
        summary["recall_at_k"],
        summary["mean_latency_s"],
        summary["mean_prompt_tokens"],
        summary["mean_completion_tokens"],
    ]


_HEADERS = [
    "mode",
    "split",
    "n",
    "match",
    "abstention",
    "stale_error",
    "recall_at_k",
    "latency_s",
    "prompt_tokens",
    "completion_tokens",
]


def render_markdown(report: dict[str, Any]) -> str:
    """Render the report as a short Markdown document with tables."""
    lines = [
        f"# {report['dataset']}",
        "",
        report["description"],
        "",
        f"Seed `{report['seed']}`. Model `{report['model']}`. "
        f"k={report['k']}. Judge: `{report['judge_model'] or 'off'}`.",
        "",
        report["methodology"],
        "",
        "## Retrieval",
        "",
    ]
    for question_type, policy in report["retrieval_policy"].items():
        lines.append(f"- `{question_type}`: {policy}")
    lines.extend(["", "## Results", ""])

    overall_rows: list[list[object]] = []
    split_rows: list[list[object]] = []
    for mode, payload in report["modes"].items():
        if payload.get("skipped"):
            lines.append(f"Skipped `{mode}`: {payload.get('reason', '')}")
            lines.append("")
            continue
        if payload.get("error"):
            lines.append(f"`{mode}` failed: {payload['error']}")
            lines.append("")
            continue
        summary = payload["summary"]
        overall_rows.append(_summary_row(mode, "overall", summary["overall"]))
        for split, values in summary["by_type"].items():
            split_rows.append(_summary_row(mode, f"type:{split}", values))
        for split, values in summary["by_difficulty"].items():
            split_rows.append(_summary_row(mode, f"difficulty:{split}", values))

    if overall_rows:
        lines.append(_table(_HEADERS, overall_rows))
        lines.append("")
    if split_rows:
        lines.append(_table(_HEADERS, split_rows))
        lines.append("")
    return "\n".join(lines)


def dump_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=False) + "\n"
