"""Unit tests for the quote answer format. The real model is never loaded."""
import json
from pathlib import Path

import pytest

import coach
import coach_prompts
import coach_retrieval
import evaluate_coach
from coach_prompts import BASELINE, QUOTE, SPECIALIZED
from test_coach import FakeGenerator, MIDPOINT_QUESTION

ROOT = Path(__file__).resolve().parent.parent
FRACTION_QUESTION = (
    "Can I submit a fractional guess, and does it use a round?"
)


def section_text(source_id):
    for section in coach_retrieval.default_index().sections:
        if section.source_id == source_id:
            return section.text
    raise KeyError(source_id)


def reply(source_id, quote):
    return json.dumps({"source_id": source_id, "quote": quote})


def ask(answer, question=FRACTION_QUESTION, profile=BASELINE):
    return coach.ask_coach(question, profile=profile, answer_format=QUOTE,
                           generator=FakeGenerator(answer))


def failed_check(result):
    return next(item for item in result.checks if not item["passed"])


VALID = section_text("rules-valid-guesses")


def test_full_quote_is_accepted():
    answer = reply("rules-valid-guesses", " ".join(VALID.split()))

    result = ask(answer)

    assert result.status == coach.ANSWERED
    assert result.accepted_quote == {
        "source_id": "rules-valid-guesses",
        "quote": " ".join(VALID.split()),
    }
    assert result.answer == answer  # the raw answer is kept unchanged


def test_only_whitespace_differences_are_accepted():
    spaced = "  " + VALID.replace(" ", "   ").replace("\n", " \n\n ") + "\n"

    result = ask(reply("rules-valid-guesses", spaced))

    assert result.status == coach.ANSWERED
    assert result.accepted_quote["quote"] == spaced


@pytest.mark.parametrize(
    "changed_text",
    [
        VALID.replace("does not use up", "does use up"),
        VALID.rsplit(" A rejected guess", 1)[0],
        VALID.replace("4.5", "4.6"),
    ],
    ids=["removed-negation", "shortened-section", "changed-number"],
)
def test_changed_text_is_rejected(changed_text):
    assert changed_text != VALID
    answer = reply("rules-valid-guesses", changed_text)

    result = ask(answer)

    assert result.status == coach.VALIDATION_FAILED
    assert result.accepted_quote is None
    assert result.answer == answer
    assert failed_check(result)["key"] == "exact_full_quote"


def test_unknown_source_is_rejected():
    result = ask(reply("rules-made-up", VALID))

    assert result.status == coach.VALIDATION_FAILED
    assert result.accepted_quote is None
    assert failed_check(result)["key"] == "allowed_source"


@pytest.mark.parametrize(
    "answer, key",
    [
        ("Sure! " + reply("rules-valid-guesses", VALID), "valid_json"),
        ('{"source_id": "rules-valid-guesses", "quote": ', "valid_json"),
        (json.dumps({"source_id": "rules-valid-guesses", "quote": VALID,
                     "note": "x"}), "two_keys"),
        (json.dumps({"source_id": 7, "quote": VALID}), "types"),
        (json.dumps(["rules-valid-guesses", VALID]), "two_keys"),
    ],
    ids=["text-around-json", "broken-json", "extra-key", "wrong-type",
         "not-an-object"],
)
def test_wrong_format_is_rejected(answer, key):
    result = ask(answer)

    assert result.status == coach.VALIDATION_FAILED
    assert result.accepted_quote is None
    assert result.answer == answer
    assert failed_check(result)["key"] == key


def test_null_pair_means_abstained():
    result = ask(json.dumps({"source_id": None, "quote": None}))

    assert result.status == coach.ABSTAINED
    assert result.generator_called is True
    assert result.accepted_quote is None
    assert "model's choice" in result.note


def test_example_source_is_not_allowed_automatically():
    # rules-new-duel is a quote-example source, not found for this question.
    current = {result.section.source_id for result in coach_retrieval.search(
        MIDPOINT_QUESTION, coach.TOP_K)}
    assert "rules-new-duel" not in current
    answer = reply("rules-new-duel", section_text("rules-new-duel"))

    result = ask(answer, question=MIDPOINT_QUESTION, profile=SPECIALIZED)

    assert result.status == coach.VALIDATION_FAILED
    assert failed_check(result)["key"] == "allowed_source"


def test_quote_messages_settings_and_examples():
    base_fake = FakeGenerator(reply("rules-valid-guesses", VALID))
    spec_fake = FakeGenerator(reply("rules-valid-guesses", VALID))
    coach.ask_coach(FRACTION_QUESTION, profile=BASELINE, answer_format=QUOTE,
                    generator=base_fake)
    coach.ask_coach(FRACTION_QUESTION, profile=SPECIALIZED,
                    answer_format=QUOTE, generator=spec_fake)
    base, spec = base_fake.calls[0], spec_fake.calls[0]

    # The same system prompt, current turn and token limit for both.
    assert base["messages"][0]["content"] == coach_prompts.QUOTE_SYSTEM_PROMPT
    assert spec["messages"][0] == base["messages"][0]
    assert spec["messages"][-1] == base["messages"][-1]
    assert base["max_new_tokens"] == spec["max_new_tokens"] == 192
    assert len(base["messages"]) == 2
    # Specialized adds the three quote examples: the full section as JSON.
    examples = spec["messages"][1:-1]
    assert len(examples) == 6
    for example, answer in zip(coach_prompts.FEW_SHOT_EXAMPLES,
                               examples[1::2]):
        data = json.loads(answer["content"])
        assert set(data) == {"source_id", "quote"}
        assert data["source_id"] == example["source_ids"][0]
        assert data["quote"] == " ".join(
            section_text(data["source_id"]).split()
        )
        assert "fraction" not in example["question"].lower()


def test_quote_needs_retrieval():
    with pytest.raises(ValueError, match="quote format needs found sources"):
        coach.ask_coach(FRACTION_QUESTION, use_retrieval=False,
                        answer_format=QUOTE, generator=FakeGenerator("x"))


def test_text_format_keeps_the_earlier_behavior():
    saved = {case["name"]: case for case in json.loads(
        (ROOT / "artifacts" / "rag_smoke.json").read_text(encoding="utf-8")
    )["cases"]}["rag"]
    fake = FakeGenerator("No [reliability-midpoint-not-required].")

    result = coach.ask_coach(saved["question"], generator=fake)

    assert result.answer_format == coach_prompts.TEXT
    assert fake.calls[0]["messages"] == saved["messages"]
    assert fake.calls[0]["max_new_tokens"] == 128
    assert result.status == coach.ANSWERED
    assert result.accepted_quote is None


def test_quote_comparison_uses_one_search_per_question():
    searches = []

    def counting_search(question, top_k):
        searches.append(question)
        return coach_retrieval.search(question, top_k)

    fake = FakeGenerator(reply("rules-valid-guesses", VALID))
    report = evaluate_coach.run_comparison(
        evaluate_coach.FRACTION_REGRESSION_QUESTIONS, generator=fake,
        search=counting_search, suite="fraction-regression",
        answer_format=QUOTE,
    )

    assert searches == list(evaluate_coach.FRACTION_REGRESSION_QUESTIONS)
    assert report["generations"] == 6 == len(fake.calls)
    assert report["answer_format"] == QUOTE
    assert report["system_prompt"] == coach_prompts.QUOTE_SYSTEM_PROMPT
    for row in report["results"]:
        assert row["same_sources_for_both_profiles"]
        assert row["same_current_turn_for_both_profiles"]
    summary = report["summary"][BASELINE]
    assert set(summary) == {
        "answers", "valid_json", "allowed_source", "exact_full_quote",
        "answered", "validation_failed", "abstained",
        "mean_generated_tokens",
    }
    # The fake always quotes rules-valid-guesses, found for all 3 questions.
    assert summary["exact_full_quote"] == summary["answered"] == 3
