"""Prompts shared by every memory mode."""

from __future__ import annotations

SYSTEM_PROMPT = (
    "You answer questions about a small workshop memory. "
    "Use only the memory context. "
    "If the context does not contain the answer, reply exactly: not in memory. "
    "If two context items conflict and neither is outdated, name both and say they conflict. "
    "When a fact was updated, answer with the current fact unless the question asks about an earlier time. "
    "Be brief."
)

JUDGE_SYSTEM_PROMPT = (
    "You grade a short answer against a gold answer. "
    'Reply with JSON only: {"correct": true or false, "reason": "one sentence"}. '
    "Mark correct when the prediction states the same fact as the gold answer. "
    "For a conflict, both sides must appear. "
    "For abstention, the prediction must refuse because the fact is not in memory."
)


def memory_block(contexts: list[str]) -> str:
    if not contexts:
        return "(empty)"
    return "\n".join(f"- {text}" for text in contexts)


def answer_messages(question: str, contexts: list[str]) -> list[dict[str, str]]:
    user = f"Memory context:\n{memory_block(contexts)}\n\nQuestion: {question}\nAnswer:"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def judge_messages(question: str, gold: str, prediction: str) -> list[dict[str, str]]:
    user = f"Question: {question}\nGold answer: {gold}\nPrediction: {prediction}\n"
    return [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
