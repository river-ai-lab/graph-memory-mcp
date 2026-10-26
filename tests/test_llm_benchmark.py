"""Scenario B scoring and dataset tests. No model and no graph server."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

_LLM_ROOT = Path(__file__).resolve().parent / "benchmarks" / "llm"
if str(_LLM_ROOT) not in sys.path:
    sys.path.insert(0, str(_LLM_ROOT))

from benchlib.adapters import (  # noqa: E402
    HashingEmbedder,
    NoMemoryAdapter,
    RagAdapter,
    availability,
)
from benchlib.dataset import load_dataset, validate_dataset  # noqa: E402
from benchlib.llm import Completion  # noqa: E402
from benchlib.report import render_markdown  # noqa: E402
from benchlib.runner import build_report, parse_judge, run_mode  # noqa: E402
from benchlib.scoring import (  # noqa: E402
    answers_match,
    estimate_tokens,
    is_abstention,
    normalize,
    recall_at_k,
    score_prediction,
)


class _Scripted:
    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers

    def complete(self, messages):
        user = messages[-1]["content"]
        question = user.split("Question:", 1)[1].split("Answer:", 1)[0].strip()
        text = self.answers.get(question, "not in memory")
        return Completion(
            text=text,
            latency_s=0.01,
            prompt_tokens=estimate_tokens(user),
            completion_tokens=estimate_tokens(text),
            token_source="estimate",
        )


def test_dataset_loads_and_covers_types():
    dataset = load_dataset()
    assert dataset.name == "workshop-micro"
    assert dataset.seed == 1729
    assert dataset.retrieval_policy["abstention"] == "not_required"
    for question_type in (
        "single_fact",
        "updated_fact",
        "contradiction",
        "multi_hop",
        "temporal",
    ):
        assert dataset.retrieval_policy[question_type] == "required"
    types = {question.type for question in dataset.questions}
    difficulties = {question.difficulty for question in dataset.questions}
    assert types == {
        "single_fact",
        "updated_fact",
        "contradiction",
        "multi_hop",
        "temporal",
        "abstention",
    }
    assert difficulties == {"easy", "medium", "hard"}
    assert any(fact.distractor for fact in dataset.facts)
    assert any(fact.status == "outdated" for fact in dataset.facts)
    abstention = [q for q in dataset.questions if q.type == "abstention"]
    assert abstention and all(not q.needs_retrieval for q in abstention)
    assert all(q.needs_retrieval for q in dataset.questions if q.type != "abstention")


def test_dataset_rejects_unknown_gold_fact():
    raw = json.loads((_LLM_ROOT / "dataset.json").read_text(encoding="utf-8"))
    broken = copy.deepcopy(raw)
    broken["questions"][0]["gold_fact_ids"] = ["missing"]
    with pytest.raises(ValueError, match="unknown"):
        validate_dataset(broken)


def test_dataset_rejects_abstention_with_gold_facts():
    raw = json.loads((_LLM_ROOT / "dataset.json").read_text(encoding="utf-8"))
    broken = copy.deepcopy(raw)
    for question in broken["questions"]:
        if question["type"] == "abstention":
            question["gold_fact_ids"] = ["f_badge"]
            break
    with pytest.raises(ValueError, match="abstention"):
        validate_dataset(broken)


def test_normalize_and_match():
    assert normalize("  SAE-30! ") == "sae 30"
    assert answers_match("The badge is 4412.", ["4412"])
    assert not answers_match("not", ["not in memory"])
    assert answers_match("not in memory", ["not in memory"])
    assert is_abstention("I do not know; it is not in memory")
    assert not is_abstention("4412")
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1


def test_score_updated_fact_stale_and_current():
    question = next(item for item in load_dataset().questions if item.id == "q_coffee")
    current = score_prediction(
        question, "The machine is a Moccamaster.", ["f_coffee_new"], 4
    )
    assert current["match"] is True
    assert current["stale_error"] is False
    assert current["recall_at_k"] == 1.0
    stale = score_prediction(question, "It is still a Breville.", ["f_coffee_old"], 4)
    assert stale["match"] is False
    assert stale["stale_error"] is True
    assert stale["recall_at_k"] == 0.0
    assert score_prediction(question, "not in memory", None, 4)["recall_at_k"] is None


def test_score_contradiction_and_abstention():
    dataset = load_dataset()
    oil = next(item for item in dataset.questions if item.id == "q_oil")
    both = score_prediction(
        oil,
        "The notes conflict: SAE 30 and SAE 10W.",
        ["f_oil_30", "f_oil_10w", "f_parking"],
        4,
    )
    assert both["match"] is True
    assert both["recall_at_k"] == 1.0
    one_side = score_prediction(oil, "SAE 30", ["f_oil_30"], 4)
    assert one_side["match"] is False
    assert one_side["recall_at_k"] == 0.5
    address = next(item for item in dataset.questions if item.id == "q_address")
    refused = score_prediction(address, "not in memory", None, 4)
    assert refused["match"] is True
    assert refused["abstention_correct"] is True
    assert refused["recall_at_k"] is None
    guessed = score_prediction(address, "12 Oak Street", [], 4)
    assert guessed["abstention_correct"] is False


def test_recall_at_k_bounds():
    assert recall_at_k(["a", "b"], ["b", "c"], 1) == 0.0
    assert recall_at_k(["a", "b"], ["b", "c"], 2) == 0.5
    assert recall_at_k(None, ["b"], 2) is None
    assert recall_at_k(["b"], [], 2) is None


def test_hashing_retrieval_is_deterministic():
    dataset = load_dataset()
    first = RagAdapter(seed=dataset.seed)
    second = RagAdapter(seed=dataset.seed)
    first.ingest(dataset)
    second.ingest(dataset)
    query = "Nora Chen's badge number is 4412."
    left = [hit.fact_id for hit in first.search(query, 3)]
    right = [hit.fact_id for hit in second.search(query, 3)]
    assert left == right
    assert left[0] == "f_badge"
    same = HashingEmbedder(seed=dataset.seed)
    vector = same.embed(query)
    assert vector.shape == (256,)
    assert abs(float(vector @ vector) - 1.0) < 1e-9
    assert NoMemoryAdapter().search(query, 3) == []


def test_optional_adapters_skip_when_missing():
    for name in ("mem0", "graphiti", "zep", "letta", "cognee"):
        ok, reason = availability(name)
        if not ok:
            assert "not installed" in reason
    assert availability("none") == (True, "")
    assert availability("rag") == (True, "")
    assert availability("graph") == (True, "")
    ok, reason = availability("nope")
    assert ok is False
    assert "unknown" in reason


def test_run_mode_none_and_rag_without_a_model():
    dataset = load_dataset()
    answers = {question.text: "not in memory" for question in dataset.questions}
    answers["What is Nora Chen's badge number?"] = "4412"
    client = _Scripted(answers)
    none = run_mode("none", dataset, client, k=4)
    assert "error" not in none
    badge = next(row for row in none["questions"] if row["id"] == "q_badge")
    assert badge["match"] is True
    assert badge["retrieved_fact_ids"] is None
    assert badge["recall_at_k"] is None
    address = next(row for row in none["questions"] if row["id"] == "q_address")
    assert address["abstention_correct"] is True
    rag = run_mode("rag", dataset, client, k=4)
    rag_badge = next(row for row in rag["questions"] if row["id"] == "q_badge")
    assert rag_badge["retrieved_fact_ids"]
    assert "f_badge" in rag_badge["retrieved_fact_ids"]
    report = build_report(
        dataset,
        {"none": none, "mem0": {"skipped": True, "reason": "mem0 is not installed"}},
        model="scripted",
        judge_model=None,
        k=4,
        include_outdated=False,
    )
    markdown = render_markdown(report)
    assert "| mode | split | n | match |" in markdown
    assert "Skipped `mem0`" in markdown
    assert parse_judge('```json\n{"correct": true, "reason": "same"}\n```') is True
    assert parse_judge("no") is None


def test_dataset_integrity_and_balance():
    dataset = load_dataset()
    facts = dataset.fact_map()
    episodes = {episode.id for episode in dataset.episodes}
    for fact in dataset.facts:
        assert fact.episode_id in episodes
    counts: dict[str, int] = {}
    for question in dataset.questions:
        counts[question.type] = counts.get(question.type, 0) + 1
        for fact_id in question.gold_fact_ids:
            assert fact_id in facts
        if question.type == "temporal":
            assert question.stale_answers
    assert len(dataset.questions) >= 40
    assert max(counts.values()) - min(counts.values()) <= 2
    by_difficulty = {question.difficulty for question in dataset.questions}
    assert by_difficulty == {"easy", "medium", "hard"}
