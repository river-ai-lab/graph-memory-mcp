"""Structural retrieval benchmark. Opt-in: pytest -m structural_bench."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent / "benchmarks" / "structural"


def test_generator_is_deterministic(tmp_path):
    fresh = tmp_path / "dataset.json"
    subprocess.run(
        [sys.executable, str(ROOT / "generate.py"), str(fresh)],
        check=True,
        capture_output=True,
    )
    assert fresh.read_bytes() == (ROOT / "dataset.json").read_bytes()


def test_dataset_shape():
    data = json.loads((ROOT / "dataset.json").read_text())
    ids = {f["id"] for f in data["core"]["facts"]}
    assert 90 <= len(ids) <= 120
    assert data["noise_summary"]["facts"] == 10_000
    assert 35 <= len(data["questions"]) <= 45
    for q in data["questions"]:
        assert set(q["gold"]) <= ids


@pytest.mark.structural_bench
@pytest.mark.skipif(
    os.environ.get("STRUCTURAL_BENCH") != "1",
    reason="set STRUCTURAL_BENCH=1 to run the structural benchmark",
)
def test_structural_benchmark_runs(tmp_path):
    out = tmp_path / "res.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "run.py"),
            "--levels",
            "0",
            "--out",
            str(out),
            "--checkpoint",
            str(tmp_path / "ck.json"),
        ],
        check=True,
        env={**os.environ, "GRAPH_BACKEND": "falkordb"},
    )
    res = json.loads(out.read_text())
    assert res["levels"]["0"]["systems"]["rag"]["by_type"]["all"]["n"] == len(
        json.loads((ROOT / "dataset.json").read_text())["questions"]
    )
