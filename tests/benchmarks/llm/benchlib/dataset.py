"""Load and validate the Scenario B micro-dataset."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

QUESTION_TYPES = (
    "single_fact",
    "updated_fact",
    "contradiction",
    "multi_hop",
    "temporal",
    "abstention",
)
DIFFICULTIES = ("easy", "medium", "hard")
FACT_STATUSES = ("active", "outdated")
RETRIEVAL_VALUES = ("required", "not_required")

DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "dataset.json"


@dataclass(frozen=True)
class Turn:
    role: str
    text: str


@dataclass(frozen=True)
class Episode:
    id: str
    at: str
    turns: tuple[Turn, ...]


@dataclass(frozen=True)
class Fact:
    id: str
    text: str
    status: str
    episode_id: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    supersedes: str | None = None
    contradicts: str | None = None
    follows_from: str | None = None
    distractor: bool = False


@dataclass(frozen=True)
class Question:
    id: str
    difficulty: str
    type: str
    text: str
    gold_answers: tuple[str, ...]
    gold_fact_ids: tuple[str, ...]
    stale_answers: tuple[str, ...]
    require_all: tuple[str, ...]
    needs_retrieval: bool


@dataclass(frozen=True)
class Dataset:
    name: str
    version: int
    seed: int
    description: str
    retrieval_policy: dict[str, str]
    episodes: tuple[Episode, ...]
    facts: tuple[Fact, ...]
    questions: tuple[Question, ...]

    def fact_map(self) -> dict[str, Fact]:
        return {fact.id: fact for fact in self.facts}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _string_list(value: object, field: str) -> tuple[str, ...]:
    _require(isinstance(value, list), f"{field} must be a list")
    items: list[str] = []
    for item in value:  # type: ignore[union-attr]
        _require(isinstance(item, str) and item.strip(), f"{field} items must be text")
        items.append(item.strip())
    return tuple(items)


def validate_dataset(raw: dict) -> Dataset:
    """Validate a decoded dataset document and return it typed."""
    _require(isinstance(raw, dict), "dataset must be an object")
    name = raw.get("name")
    _require(isinstance(name, str) and name.strip(), "name is required")
    version = raw.get("version")
    _require(isinstance(version, int), "version must be an integer")
    seed = raw.get("seed")
    _require(isinstance(seed, int), "seed must be an integer")
    description = raw.get("description")
    _require(
        isinstance(description, str) and description.strip(), "description is required"
    )

    policy = raw.get("retrieval_policy")
    _require(isinstance(policy, dict), "retrieval_policy must be an object")
    for question_type in QUESTION_TYPES:
        value = policy.get(question_type)
        _require(
            value in RETRIEVAL_VALUES,
            f"retrieval_policy.{question_type} must be required or not_required",
        )
    extra_policy = set(policy) - set(QUESTION_TYPES)
    _require(not extra_policy, f"unknown retrieval_policy keys: {sorted(extra_policy)}")

    episodes_raw = raw.get("episodes")
    _require(
        isinstance(episodes_raw, list) and episodes_raw,
        "episodes must be a non-empty list",
    )
    episodes: list[Episode] = []
    episode_ids: set[str] = set()
    for episode in episodes_raw:
        _require(isinstance(episode, dict), "episode must be an object")
        episode_id = episode.get("id")
        _require(isinstance(episode_id, str) and episode_id, "episode id is required")
        _require(episode_id not in episode_ids, f"duplicate episode id {episode_id}")
        episode_ids.add(episode_id)
        at = episode.get("at")
        _require(isinstance(at, str) and at, f"{episode_id} at is required")
        turns_raw = episode.get("turns")
        _require(
            isinstance(turns_raw, list) and turns_raw,
            f"{episode_id} turns are required",
        )
        turns: list[Turn] = []
        for turn in turns_raw:
            _require(isinstance(turn, dict), f"{episode_id} turn must be an object")
            role = turn.get("role")
            text = turn.get("text")
            _require(
                role in {"user", "assistant"}, f"{episode_id} turn role is invalid"
            )
            _require(
                isinstance(text, str) and text.strip(),
                f"{episode_id} turn text is required",
            )
            turns.append(Turn(role=role, text=text.strip()))
        episodes.append(Episode(id=episode_id, at=at, turns=tuple(turns)))

    facts_raw = raw.get("facts")
    _require(
        isinstance(facts_raw, list) and facts_raw, "facts must be a non-empty list"
    )
    facts: list[Fact] = []
    fact_ids: set[str] = set()
    for fact in facts_raw:
        _require(isinstance(fact, dict), "fact must be an object")
        fact_id = fact.get("id")
        _require(isinstance(fact_id, str) and fact_id, "fact id is required")
        _require(fact_id not in fact_ids, f"duplicate fact id {fact_id}")
        fact_ids.add(fact_id)
        text = fact.get("text")
        _require(isinstance(text, str) and text.strip(), f"{fact_id} text is required")
        status = fact.get("status")
        _require(
            status in FACT_STATUSES, f"{fact_id} status must be active or outdated"
        )
        episode_id = fact.get("episode_id")
        _require(
            episode_id is None or episode_id in episode_ids,
            f"{fact_id} episode_id is unknown",
        )
        facts.append(
            Fact(
                id=fact_id,
                text=text.strip(),
                status=status,
                episode_id=episode_id,
                valid_from=fact.get("valid_from"),
                valid_until=fact.get("valid_until"),
                supersedes=fact.get("supersedes"),
                contradicts=fact.get("contradicts"),
                follows_from=fact.get("follows_from"),
                distractor=bool(fact.get("distractor", False)),
            )
        )

    for fact in facts:
        for field in ("supersedes", "contradicts", "follows_from"):
            target = getattr(fact, field)
            _require(
                target is None or target in fact_ids,
                f"{fact.id} {field} points at unknown fact {target}",
            )
            _require(target != fact.id, f"{fact.id} {field} points at itself")

    questions_raw = raw.get("questions")
    _require(
        isinstance(questions_raw, list) and questions_raw,
        "questions must be a non-empty list",
    )
    questions: list[Question] = []
    question_ids: set[str] = set()
    seen_types: set[str] = set()
    seen_difficulties: set[str] = set()
    for question in questions_raw:
        _require(isinstance(question, dict), "question must be an object")
        question_id = question.get("id")
        _require(
            isinstance(question_id, str) and question_id, "question id is required"
        )
        _require(
            question_id not in question_ids, f"duplicate question id {question_id}"
        )
        question_ids.add(question_id)
        difficulty = question.get("difficulty")
        qtype = question.get("type")
        _require(difficulty in DIFFICULTIES, f"{question_id} difficulty is invalid")
        _require(qtype in QUESTION_TYPES, f"{question_id} type is invalid")
        seen_types.add(qtype)
        seen_difficulties.add(difficulty)
        text = question.get("text")
        _require(
            isinstance(text, str) and text.strip(), f"{question_id} text is required"
        )
        gold_answers = _string_list(
            question.get("gold_answers"), f"{question_id} gold_answers"
        )
        gold_fact_ids = _string_list(
            question.get("gold_fact_ids", []), f"{question_id} gold_fact_ids"
        )
        stale_answers = _string_list(
            question.get("stale_answers", []), f"{question_id} stale_answers"
        )
        require_all = _string_list(
            question.get("require_all", []), f"{question_id} require_all"
        )
        for fact_id in gold_fact_ids:
            _require(
                fact_id in fact_ids, f"{question_id} gold fact {fact_id} is unknown"
            )
            _require(
                not next(item.distractor for item in facts if item.id == fact_id),
                f"{question_id} gold fact {fact_id} is a distractor",
            )
        needs = policy[qtype] == "required"
        if qtype == "abstention":
            _require(
                not gold_fact_ids, f"{question_id} abstention must not name gold facts"
            )
            _require(
                not needs, f"{question_id} abstention retrieval must be not_required"
            )
        else:
            _require(needs, f"{question_id} retrieval must be required")
            _require(gold_fact_ids, f"{question_id} needs at least one gold fact")
        if qtype == "updated_fact":
            _require(stale_answers, f"{question_id} needs stale_answers")
        if qtype == "multi_hop":
            _require(
                len(gold_fact_ids) >= 2, f"{question_id} needs at least two gold facts"
            )
        if qtype == "contradiction":
            _require(
                len(gold_fact_ids) >= 2,
                f"{question_id} needs both sides of the conflict",
            )
            _require(require_all, f"{question_id} needs require_all mentions")
        questions.append(
            Question(
                id=question_id,
                difficulty=difficulty,
                type=qtype,
                text=text.strip(),
                gold_answers=gold_answers,
                gold_fact_ids=gold_fact_ids,
                stale_answers=stale_answers,
                require_all=require_all,
                needs_retrieval=needs,
            )
        )

    _require(
        seen_types == set(QUESTION_TYPES), "dataset must include every question type"
    )
    _require(
        seen_difficulties == set(DIFFICULTIES),
        "dataset must include every difficulty",
    )
    _require(any(fact.distractor for fact in facts), "dataset must include distractors")
    _require(
        any(fact.status == "outdated" for fact in facts),
        "dataset must include outdated facts",
    )
    _require(
        any(fact.contradicts for fact in facts),
        "dataset must include a contradiction",
    )

    return Dataset(
        name=name.strip(),
        version=version,
        seed=seed,
        description=description.strip(),
        retrieval_policy=dict(policy),
        episodes=tuple(episodes),
        facts=tuple(facts),
        questions=tuple(questions),
    )


def load_dataset(path: Path | None = None) -> Dataset:
    """Load the micro-dataset from JSON."""
    dataset_path = path or DEFAULT_DATASET
    with dataset_path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    return validate_dataset(raw)
