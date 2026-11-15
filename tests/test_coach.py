"""Unit tests for the coach. The real model is never loaded here."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

import coach
import coach_model

ROOT = Path(__file__).resolve().parent.parent
MIDPOINT_QUESTION = (
    "Must the inspector require Vector to guess the exact midpoint?"
)
NO_HIT_QUESTION = "How do I bake sourdough bread?"


class FakeGenerator:
    """Stands in for the local model and records every call."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def generate(self, messages, max_new_tokens):
        self.calls.append({"messages": messages,
                           "max_new_tokens": max_new_tokens})
        return coach_model.Generation(
            text=self.reply,
            raw_text=self.reply,
            prompt_tokens=100,
            generated_tokens=20,
            max_new_tokens=max_new_tokens,
            thinking_off=True,
            load_seconds=0.0,
            generate_seconds=0.0,
        )


class FailingGenerator:
    def generate(self, messages, max_new_tokens):
        raise AssertionError("the model must not be called")


def no_search(question, top_k):
    raise AssertionError("the knowledge search must not be called")


def test_found_texts_and_ids_go_to_the_generator():
    fake = FakeGenerator(
        "No. It only checks that each guess is inside the range "
        "[reliability-midpoint-not-required]."
    )

    result = coach.ask_coach(MIDPOINT_QUESTION, generator=fake)

    assert len(fake.calls) == 1
    user_message = fake.calls[0]["messages"][-1]["content"]
    assert result.sources
    assert result.sources[0]["source_id"] == (
        "reliability-midpoint-not-required"
    )
    for source in result.sources:
        assert f"[{source['source_id']}]" in user_message
        assert source["text"] in user_message
    assert MIDPOINT_QUESTION in user_message
    assert result.status == coach.ANSWERED
    assert result.citations == ["reliability-midpoint-not-required"]
    assert result.answer == fake.reply


@pytest.mark.parametrize(
    "reply",
    [
        "Yes, it must [made-up-source].",
        "No [reliability-midpoint-not-required], see [rules-made-up].",
    ],
    ids=["only-unknown", "valid-and-unknown"],
)
def test_unknown_citation_is_blocked(reply):
    result = coach.ask_coach(MIDPOINT_QUESTION,
                             generator=FakeGenerator(reply))

    assert result.status == coach.VALIDATION_FAILED
    assert result.answer == reply  # the raw answer is kept, not fixed
    unknown_check = next(item for item in result.checks
                         if item["check"].startswith("every cited ID"))
    assert unknown_check["passed"] is False
    assert unknown_check["unknown_ids"]


def test_missing_citation_is_blocked_with_retrieval():
    reply = "No, the inspector only checks that the guess is in the range."

    result = coach.ask_coach(MIDPOINT_QUESTION,
                             generator=FakeGenerator(reply))

    assert result.status == coach.VALIDATION_FAILED
    assert result.answer == reply
    assert result.citations == []


def test_no_hit_abstains_without_calling_the_model():
    result = coach.ask_coach(NO_HIT_QUESTION, generator=FailingGenerator())

    assert result.status == coach.ABSTAINED
    assert result.generator_called is False
    assert result.answer is None
    assert result.messages is None
    assert result.sources == []
    assert "rule of the program, not an answer from the model" in result.note


def test_baseline_skips_search_and_calls_the_generator():
    fake = FakeGenerator("No, I do not think it has to be the midpoint.")

    baseline = coach.ask_coach(MIDPOINT_QUESTION, use_retrieval=False,
                               generator=fake, search=no_search)

    assert len(fake.calls) == 1
    messages = fake.calls[0]["messages"]
    assert messages[-1]["content"] == f"Question: {MIDPOINT_QUESTION}"
    assert "Sources:" not in messages[-1]["content"]
    assert baseline.mode == coach.MODE_NO_RETRIEVAL
    assert baseline.sources == []
    # No sources were given, so a missing citation is not an error.
    assert baseline.status == coach.ANSWERED_WITHOUT_RETRIEVAL

    # Same instructions and settings as with retrieval.
    rag_fake = FakeGenerator("No [reliability-midpoint-not-required].")
    coach.ask_coach(MIDPOINT_QUESTION, generator=rag_fake)
    assert rag_fake.calls[0]["messages"][0] == messages[0]
    assert (rag_fake.calls[0]["max_new_tokens"]
            == fake.calls[0]["max_new_tokens"])


def test_missing_dependencies_are_explained(monkeypatch, capsys):
    monkeypatch.setattr(coach_model, "missing_dependencies",
                        lambda: ["torch"])
    monkeypatch.setattr(coach_model, "get_generator",
                        lambda: coach_model.LocalGenerator())

    exit_code = coach.main(["--question", MIDPOINT_QUESTION])

    assert exit_code == 2
    errors = capsys.readouterr().err
    assert "Missing coach dependencies: torch" in errors
    assert "pip install -r requirements-coach.txt" in errors


def test_missing_model_is_explained(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(coach_model, "missing_dependencies", lambda: [])
    monkeypatch.setattr(coach_model, "MODEL_DIR", tmp_path / "no-model")
    monkeypatch.setattr(coach_model, "get_generator",
                        lambda: coach_model.LocalGenerator())

    exit_code = coach.main(["--question", MIDPOINT_QUESTION,
                            "--no-retrieval"])

    assert exit_code == 2
    errors = capsys.readouterr().err
    assert "does not exist" in errors
    assert "python coach_model.py download" in errors


def test_cli_writes_a_json_report(monkeypatch, tmp_path, capsys):
    fake = FakeGenerator("No [reliability-midpoint-not-required].")
    monkeypatch.setattr(coach_model, "get_generator", lambda: fake)
    report_path = tmp_path / "report.json"

    exit_code = coach.main(["--question", MIDPOINT_QUESTION,
                            "--output", str(report_path)])

    assert exit_code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == coach.ANSWERED
    assert report["generator_called"] is True
    assert report["generation"]["model"] == coach_model.MODEL_ID
    assert report["generation"]["revision"] == coach_model.MODEL_REVISION
    assert "status:    answered" in capsys.readouterr().out


def test_importing_the_coach_does_not_load_torch():
    code = ("import sys, coach, coach_model; "
            "print('torch' in sys.modules, 'transformers' in sys.modules, "
            "coach_model.get_generator().loaded)")
    completed = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                               capture_output=True, text=True, timeout=60)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "False False False"
