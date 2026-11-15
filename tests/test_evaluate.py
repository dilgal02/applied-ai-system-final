import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import evaluate

ROOT = Path(__file__).resolve().parent.parent
ALL_CASES = [
    "player-win",
    "bot-win",
    "simultaneous-win",
    "limit-draw",
    "invalid-input",
    "guardrail-blocked",
]


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "evaluate.py", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_cli_runs_all_cases_and_writes_json(tmp_path):
    report_path = tmp_path / "report.json"

    completed = run_cli("--output", str(report_path))

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "passed: 6  failed: 0  total: 6" in completed.stdout

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert [result["name"] for result in report["results"]] == ALL_CASES
    assert all(result["result"] == "PASS" for result in report["results"])
    assert report["summary"] == {"passed": 6, "failed": 0, "total": 6}

    results = {result["name"]: result for result in report["results"]}
    # The trace shows the real accepted rounds of the binary-search bot.
    assert results["player-win"]["trace"] == [
        {
            "round": 1,
            "player_guess": 40,
            "player_outcome": "Too High",
            "bot_guess": 50,
            "bot_outcome": "Too Low",
            "bot_range_before": [1, 100],
            "bot_range_after": [51, 100],
            "guardrail": "accepted",
            "status_after": "playing",
        },
        {
            "round": 2,
            "player_guess": 27,
            "player_outcome": "Win",
            "bot_guess": 75,
            "bot_outcome": "Too High",
            "bot_range_before": [51, 100],
            "bot_range_after": [51, 74],
            "guardrail": "accepted",
            "status_after": "player_won",
        },
    ]
    assert results["invalid-input"]["actual"]["exception"] == "ValueError"
    blocked = results["guardrail-blocked"]["actual"]
    assert blocked["exception"] == "GuardrailViolation"
    assert blocked["state_unchanged"] is True
    assert blocked["patch_removed"] is True

    # Same fixed data, same report: a second run gives the same bytes.
    second_path = tmp_path / "nested" / "second.json"
    assert run_cli("--output", str(second_path)).returncode == 0
    assert second_path.read_bytes() == report_path.read_bytes()

    # --case runs only the chosen scenario.
    single = run_cli("--case", "guardrail-blocked")
    assert single.returncode == 0, single.stdout + single.stderr
    assert "[1/1] guardrail-blocked" in single.stdout
    assert "passed: 1  failed: 0  total: 1" in single.stdout


def test_distorted_result_fails_with_exit_code_1(monkeypatch, capsys):
    real_safe_play_round = evaluate.safe_play_round

    def distorted(state, player_guess):
        # Fault injected only in this test: the accepted round is
        # reported as if the duel were still going on.
        return replace(
            real_safe_play_round(state, player_guess), status="playing"
        )

    monkeypatch.setattr(evaluate, "safe_play_round", distorted)

    exit_code = evaluate.main(["--case", "player-win"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "[FAIL] status is player_won" in output
    assert "result:   FAIL" in output
    assert "passed: 0  failed: 1  total: 1" in output
