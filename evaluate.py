"""Reproducible evaluation of the Number Duel engine.

Runs fixed scenarios through the real create_duel and safe_play_round
(game engine plus guardrail inspector), without Streamlit or a server.

Usage:
    python evaluate.py                         # run all scenarios
    python evaluate.py --case player-win       # run one scenario
    python evaluate.py --output report.json    # also save a JSON report

All numbers are fixed synthetic test data, and the report has no times
or random values, so every run gives the same report. A trace lists the
observed moves of the deterministic binary-search bot and the guardrail
decisions. It is not hidden reasoning of a language model.

Exit code: 0 if every selected scenario passed, 1 if any failed.
"""
import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, replace
from unittest import mock

import duel_service
from duel_logic import create_duel, play_round
from duel_service import GuardrailViolation, safe_play_round

LOW = 1
HIGH = 100

NOTES = [
    "All numbers are fixed synthetic test data (range 1-100).",
    "Traces show observed moves of the deterministic binary-search bot "
    "and guardrail decisions, not hidden reasoning of a language model.",
]


def check(description: str, passed) -> dict:
    return {"check": description, "passed": bool(passed)}


def new_duel(inputs: dict):
    return create_duel(
        low=LOW,
        high=HIGH,
        attempt_limit=inputs["attempt_limit"],
        player_secret=inputs["player_secret"],
        bot_secret=inputs["bot_secret"],
    )


def run_rounds(inputs: dict, expected: dict, trace: list) -> tuple:
    """Play every guess through safe_play_round and record each round."""
    state = new_duel(inputs)
    for guess in inputs["guesses"]:
        before = state
        # safe_play_round returns a state only after the guardrail
        # inspector accepted the step, so every round here is accepted.
        state = safe_play_round(state, guess)
        last = state.rounds[-1]
        trace.append({
            "round": len(state.rounds),
            "player_guess": last.player_guess,
            "player_outcome": last.player_outcome,
            "bot_guess": last.bot_guess,
            "bot_outcome": last.bot_outcome,
            "bot_range_before": [before.bot_low, before.bot_high],
            "bot_range_after": [state.bot_low, state.bot_high],
            "guardrail": "accepted",
            "status_after": state.status,
        })
    actual = {"status": state.status, "rounds": len(state.rounds)}
    checks = [
        check(
            f"status is {expected['status']}",
            state.status == expected["status"],
        ),
        check(
            "one accepted round per guess",
            len(state.rounds) == len(inputs["guesses"]),
        ),
    ]
    return actual, checks


def run_invalid_input(inputs: dict, expected: dict, trace: list) -> tuple:
    """A guess outside the range must be refused by the engine."""
    state = new_duel(inputs)
    snapshot = asdict(state)
    error = None
    try:
        safe_play_round(state, inputs["guess"])
    except ValueError as caught:  # GuardrailViolation is a ValueError too
        error = caught
    unchanged = asdict(state) == snapshot
    actual = {
        "exception": type(error).__name__ if error else None,
        "message": str(error) if error else None,
        "state_unchanged": unchanged,
        "rounds": len(state.rounds),
    }
    checks = [
        check("ValueError raised", isinstance(error, ValueError)),
        check(
            "error came from the engine, not GuardrailViolation",
            error is not None and not isinstance(error, GuardrailViolation),
        ),
        check("state unchanged", unchanged),
        check("no round added", len(state.rounds) == expected["rounds"]),
    ]
    return actual, checks


def run_guardrail_blocked(inputs: dict, expected: dict, trace: list) -> tuple:
    """A wrong engine result must be stopped by the real inspector."""
    state = new_duel(inputs)
    # A correct candidate for this guess, then one field made wrong.
    good = play_round(state, inputs["guess"])
    bad = replace(good, status=inputs["fake_status"])
    snapshot = asdict(state)
    error = None
    # Only the engine is replaced, and only inside this block.
    # The guardrail inspector stays real.
    with mock.patch(
        "duel_service.play_round", return_value=bad
    ) as fake_engine:
        try:
            safe_play_round(state, inputs["guess"])
        except ValueError as caught:
            error = caught
    engine_calls = fake_engine.call_count
    patch_removed = duel_service.play_round is play_round
    cause = error.__cause__ if error is not None else None
    unchanged = asdict(state) == snapshot
    actual = {
        "exception": type(error).__name__ if error else None,
        "message": str(error) if error else None,
        "inspector_reason": str(cause) if cause else None,
        "engine_calls": engine_calls,
        "state_unchanged": unchanged,
        "rounds": len(state.rounds),
        "patch_removed": patch_removed,
    }
    checks = [
        check(
            "GuardrailViolation raised",
            isinstance(error, GuardrailViolation),
        ),
        check("real inspector gave the reason", isinstance(cause, ValueError)),
        check("patched engine was called once", engine_calls == 1),
        check("state unchanged", unchanged),
        check("no round added", len(state.rounds) == expected["rounds"]),
        check("patch removed after the case", patch_removed),
    ]
    return actual, checks


# name -> (runner, inputs, expected). The order is the report order.
SCENARIOS = {
    "player-win": (
        run_rounds,
        {"player_secret": 63, "bot_secret": 27, "attempt_limit": 8,
         "guesses": [40, 27]},
        {"status": "player_won"},
    ),
    "bot-win": (
        run_rounds,
        {"player_secret": 50, "bot_secret": 27, "attempt_limit": 8,
         "guesses": [40]},
        {"status": "bot_won"},
    ),
    "simultaneous-win": (
        run_rounds,
        {"player_secret": 50, "bot_secret": 27, "attempt_limit": 8,
         "guesses": [27]},
        {"status": "draw"},
    ),
    "limit-draw": (
        run_rounds,
        {"player_secret": 63, "bot_secret": 27, "attempt_limit": 1,
         "guesses": [40]},
        {"status": "draw"},
    ),
    "invalid-input": (
        run_invalid_input,
        {"player_secret": 63, "bot_secret": 27, "attempt_limit": 8,
         "guess": 101},
        {"exception": "ValueError", "not_exception": "GuardrailViolation",
         "state_unchanged": True, "rounds": 0},
    ),
    "guardrail-blocked": (
        run_guardrail_blocked,
        {"player_secret": 63, "bot_secret": 27, "attempt_limit": 8,
         "guess": 40, "fake_status": "player_won"},
        {"exception": "GuardrailViolation", "state_unchanged": True,
         "rounds": 0},
    ),
}


def run_case(name: str) -> dict:
    """Run one scenario. Any unexpected error counts as FAIL."""
    runner, inputs, expected = SCENARIOS[name]
    trace = []
    try:
        actual, checks = runner(inputs, expected, trace)
    except Exception as error:
        actual = {"unexpected_error": f"{type(error).__name__}: {error}"}
        checks = [check("no unexpected error", False)]
    passed = bool(checks) and all(item["passed"] for item in checks)
    return {
        "name": name,
        "inputs": inputs,
        "expected": expected,
        "actual": actual,
        "trace": trace,
        "checks": checks,
        "result": "PASS" if passed else "FAIL",
    }


def format_mapping(mapping: dict) -> str:
    return ", ".join(
        f"{key}={value!r}" if isinstance(value, str) else f"{key}={value}"
        for key, value in mapping.items()
    )


def format_round(step: dict) -> str:
    before = "{}-{}".format(*step["bot_range_before"])
    after = "{}-{}".format(*step["bot_range_after"])
    return (
        f"round {step['round']}: "
        f"you {step['player_guess']} -> {step['player_outcome']} | "
        f"Vector {step['bot_guess']} -> {step['bot_outcome']} | "
        f"bot range {before} -> {after} | "
        f"guardrail: {step['guardrail']} | status: {step['status_after']}"
    )


def print_result(result: dict) -> None:
    if result["trace"]:
        print("  trace:")
        for step in result["trace"]:
            print(f"    {format_round(step)}")
    print(f"  actual:   {format_mapping(result['actual'])}")
    for item in result["checks"]:
        mark = "ok" if item["passed"] else "FAIL"
        print(f"  check:    [{mark}] {item['check']}")
    print(f"  result:   {result['result']}")
    print()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Reproducible evaluation of Number Duel."
    )
    parser.add_argument(
        "--case", choices=list(SCENARIOS), help="run only this scenario"
    )
    parser.add_argument("--output", help="save the JSON report to this path")
    args = parser.parse_args(argv)

    # Show the service's accept/reject log lines next to each case.
    # No timestamps, so the output stays the same between runs.
    logging.basicConfig(
        level=logging.INFO,
        format="  log:      %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )

    names = [args.case] if args.case else list(SCENARIOS)
    print("Number Duel evaluation")
    for note in NOTES:
        print(f"Note: {note}")
    print()

    results = []
    for index, name in enumerate(names, start=1):
        _, inputs, expected = SCENARIOS[name]
        print(f"[{index}/{len(names)}] {name}")
        print(f"  input:    {format_mapping(inputs)}")
        print(f"  expected: {format_mapping(expected)}")
        result = run_case(name)
        print_result(result)
        results.append(result)

    passed = sum(result["result"] == "PASS" for result in results)
    summary = {
        "passed": passed,
        "failed": len(results) - passed,
        "total": len(results),
    }
    print(
        f"passed: {summary['passed']}  failed: {summary['failed']}  "
        f"total: {summary['total']}"
    )

    if args.output:
        report = {
            "evaluation": "Number Duel",
            "notes": NOTES,
            "range": [LOW, HIGH],
            "results": results,
            "summary": summary,
        }
        folder = os.path.dirname(args.output)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as file:
            json.dump(report, file, indent=2)
            file.write("\n")
        print(f"report saved: {args.output}")

    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
