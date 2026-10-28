"""Run Scenario B. Scoring does not call a model; the answer client does."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Protocol

from benchlib.adapters import AdapterNotInstalled, Hit, availability, build_adapter
from benchlib.dataset import Dataset, Question
from benchlib.prompts import answer_messages, judge_messages
from benchlib.scoring import score_prediction, summarize_mode

METHODOLOGY = (
    "Every mode uses the same dataset, the same prompts, temperature 0, and the same seed. "
    "No-memory sends an empty context and does not retrieve. "
    "Plain RAG ranks every fact, including outdated facts and distractors, with a seeded hashing vector. "
    "Graph Memory stores the same facts, marks outdated facts, and searches with the server default "
    "(active facts only) unless include_outdated is set. "
    "Recall@k is omitted for no-memory and for abstention, which has no gold fact. "
    "Optional adapters (mem0, graphiti, letta, cognee) are skipped when the library is not installed "
    "and are not scored as zero."
)

_JUDGE_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class Completer(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> Any: ...


def parse_judge(text: str) -> bool | None:
    """Read {\"correct\": bool} from a judge reply. None when it is not JSON."""
    match = _JUDGE_OBJECT.search(text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    correct = payload.get("correct")
    if isinstance(correct, bool):
        return correct
    return None


def _contexts(hits: list[Hit]) -> list[str]:
    return [hit.text for hit in hits]


def answer_question(
    question: Question,
    *,
    adapter_name: str,
    hits: list[Hit] | None,
    retrieval_latency_s: float,
    completion: Any,
    k: int,
) -> dict[str, Any]:
    """Score one completion. ``hits is None`` means retrieval does not apply."""
    retrieved_ids = None if hits is None else [hit.fact_id for hit in hits]
    scored = score_prediction(question, completion.text, retrieved_ids, k)
    return {
        "id": question.id,
        "type": question.type,
        "difficulty": question.difficulty,
        "needs_retrieval": question.needs_retrieval,
        "prediction": completion.text,
        "retrieved_fact_ids": retrieved_ids,
        "retrieval_latency_s": retrieval_latency_s,
        "answer_latency_s": completion.latency_s,
        "latency_s": retrieval_latency_s + completion.latency_s,
        "prompt_tokens": completion.prompt_tokens,
        "completion_tokens": completion.completion_tokens,
        "token_source": completion.token_source,
        "mode": adapter_name,
        **scored,
    }


def run_mode(
    name: str,
    dataset: Dataset,
    client: Completer,
    *,
    k: int = 4,
    include_outdated: bool = False,
    judge: Completer | None = None,
    limit: int | None = None,
    owner_id: str = "llmbench",
) -> dict[str, Any]:
    """Ingest the dataset and answer each question. Skip optional modes that are absent."""
    ok, reason = availability(name)
    if not ok:
        return {"skipped": True, "reason": reason}
    try:
        adapter = build_adapter(name, seed=dataset.seed, owner_id=owner_id)
        adapter.reset()
        adapter.ingest(dataset)
    except AdapterNotInstalled as exc:
        return {"skipped": True, "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 — report the mode failure, do not invent scores
        return {"error": f"{type(exc).__name__}: {exc}"}

    questions = dataset.questions if limit is None else dataset.questions[:limit]
    rows: list[dict[str, Any]] = []
    for question in questions:
        if adapter.retrieves:
            started = time.perf_counter()
            try:
                hits: list[Hit] | None = adapter.search(
                    question.text, k, include_outdated=include_outdated
                )
            except Exception as exc:  # noqa: BLE001
                return {"error": f"{type(exc).__name__}: {exc}"}
            retrieval_latency_s = time.perf_counter() - started
        else:
            hits = None
            retrieval_latency_s = 0.0
        contexts = [] if hits is None else _contexts(hits)
        try:
            completion = client.complete(answer_messages(question.text, contexts))
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}
        row = answer_question(
            question,
            adapter_name=name,
            hits=hits,
            retrieval_latency_s=retrieval_latency_s,
            completion=completion,
            k=k,
        )
        if judge is not None:
            gold = "; ".join(question.gold_answers)
            try:
                verdict = judge.complete(
                    judge_messages(question.text, gold, completion.text)
                )
            except Exception as exc:  # noqa: BLE001
                return {"error": f"judge {type(exc).__name__}: {exc}"}
            row["judge_correct"] = parse_judge(verdict.text)
            row["judge_latency_s"] = verdict.latency_s
            row["latency_s"] = row["latency_s"] + verdict.latency_s
            row["prompt_tokens"] = row["prompt_tokens"] + verdict.prompt_tokens
            row["completion_tokens"] = (
                row["completion_tokens"] + verdict.completion_tokens
            )
        rows.append(row)

    summary = summarize_mode(rows)
    judged = [row["judge_correct"] for row in rows if "judge_correct" in row]
    if judged:
        known = [flag for flag in judged if flag is not None]
        summary["overall"]["judge_match_rate"] = (
            sum(1 for flag in known if flag) / len(known) if known else None
        )
    notes = getattr(adapter, "ingest_notes", [])
    payload: dict[str, Any] = {"summary": summary, "questions": rows}
    if notes:
        payload["ingest_notes"] = list(notes)
    return payload


def build_report(
    dataset: Dataset,
    modes: dict[str, Any],
    *,
    model: str,
    judge_model: str | None,
    k: int,
    include_outdated: bool,
) -> dict[str, Any]:
    return {
        "dataset": dataset.name,
        "description": dataset.description,
        "version": dataset.version,
        "seed": dataset.seed,
        "model": model,
        "judge_model": judge_model,
        "k": k,
        "include_outdated": include_outdated,
        "methodology": METHODOLOGY,
        "retrieval_policy": dataset.retrieval_policy,
        "modes": modes,
    }
