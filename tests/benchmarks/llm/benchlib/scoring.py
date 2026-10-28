"""Deterministic scoring for Scenario B. No model calls."""

from __future__ import annotations

import re
from typing import Any

from benchlib.dataset import Question

_NON_ALNUM = re.compile(r"[^a-z0-9\s]+")
_SPACE = re.compile(r"\s+")

ABSTAIN_PHRASES = (
    "not in memory",
    "not in the memory",
    "unknown",
    "i do not know",
    "i don't know",
    "cannot answer",
    "can't answer",
    "no information",
    "not enough information",
    "insufficient",
)


def normalize(text: str) -> str:
    """Lowercase, drop punctuation, and collapse whitespace."""
    cleaned = _NON_ALNUM.sub(" ", text.lower())
    return _SPACE.sub(" ", cleaned).strip()


def estimate_tokens(text: str) -> int:
    """Rough token count used when the endpoint omits usage."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def is_abstention(text: str) -> bool:
    """True when the answer refuses because memory does not contain the fact."""
    folded = normalize(text)
    if not folded:
        return False
    return any(normalize(phrase) in folded for phrase in ABSTAIN_PHRASES)


def answers_match(prediction: str, gold_answers: tuple[str, ...] | list[str]) -> bool:
    """True when the prediction equals a gold answer or either contains the other."""
    predicted = normalize(prediction)
    if not predicted:
        return False
    for gold in gold_answers:
        folded = normalize(gold)
        if not folded:
            continue
        if predicted == folded or folded in predicted:
            return True
    return False


def mentions_all(prediction: str, phrases: tuple[str, ...] | list[str]) -> bool:
    """True when every phrase appears in the prediction."""
    if not phrases:
        return False
    folded = normalize(prediction)
    return all(normalize(phrase) in folded for phrase in phrases)


def recall_at_k(
    retrieved_ids: list[str] | None, gold_ids: tuple[str, ...] | list[str], k: int
) -> float | None:
    """Fraction of gold facts present in the top k hits. None when not applicable."""
    if retrieved_ids is None or not gold_ids or k <= 0:
        return None
    gold = set(gold_ids)
    top = set(retrieved_ids[:k])
    return len(gold & top) / len(gold)


def score_prediction(
    question: Question,
    prediction: str,
    retrieved_ids: list[str] | None,
    k: int,
) -> dict[str, Any]:
    """Score one answer. ``retrieved_ids`` is None when the mode does not retrieve."""
    matched = answers_match(prediction, question.gold_answers)
    if question.require_all and mentions_all(prediction, question.require_all):
        matched = True
    abstained = is_abstention(prediction)
    if question.type == "abstention":
        abstention_correct = abstained
    else:
        abstention_correct = not abstained
    stale_error: bool | None
    if question.stale_answers:
        stale_error = (not matched) and answers_match(
            prediction, question.stale_answers
        )
    else:
        stale_error = None
    return {
        "match": matched,
        "abstained": abstained,
        "abstention_correct": abstention_correct,
        "stale_error": stale_error,
        "recall_at_k": recall_at_k(retrieved_ids, question.gold_fact_ids, k),
    }


def _mean(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present) / len(present)


def _rate(flags: list[bool | None]) -> float | None:
    present = [flag for flag in flags if flag is not None]
    if not present:
        return None
    return sum(1 for flag in present if flag) / len(present)


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate scored question rows."""
    abstention_rows = [row for row in rows if row["type"] == "abstention"]
    other_rows = [row for row in rows if row["type"] != "abstention"]
    return {
        "n": len(rows),
        "match_rate": _rate([row["match"] for row in rows]),
        "abstention_accuracy": _rate(
            [row["abstention_correct"] for row in abstention_rows]
        )
        if abstention_rows
        else None,
        "false_abstention_rate": _rate([row["abstained"] for row in other_rows])
        if other_rows
        else None,
        "stale_error_rate": _rate([row["stale_error"] for row in rows]),
        "recall_at_k": _mean([row["recall_at_k"] for row in rows]),
        "mean_latency_s": _mean([row["latency_s"] for row in rows]),
        "mean_prompt_tokens": _mean([row["prompt_tokens"] for row in rows]),
        "mean_completion_tokens": _mean([row["completion_tokens"] for row in rows]),
    }


def summarize_mode(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Overall, per-type, and per-difficulty summaries."""
    by_type = {
        key: summarize_rows([row for row in rows if row["type"] == key])
        for key in sorted({row["type"] for row in rows})
    }
    by_difficulty = {
        key: summarize_rows([row for row in rows if row["difficulty"] == key])
        for key in sorted({row["difficulty"] for row in rows})
    }
    return {
        "overall": summarize_rows(rows),
        "by_type": by_type,
        "by_difficulty": by_difficulty,
    }
