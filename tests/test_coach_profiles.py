"""Unit tests for prompt profiles. The real model is never loaded here."""
import pytest

import coach
import coach_prompts
import coach_retrieval
import evaluate_coach
from coach_prompts import BASELINE, FEW_SHOT_EXAMPLES, SPECIALIZED
from test_coach import FakeGenerator, MIDPOINT_QUESTION


def current_sections(question):
    return [result.section
            for result in coach_retrieval.search(question, coach.TOP_K)]


def test_baseline_is_the_default_profile():
    default = coach.ask_coach(MIDPOINT_QUESTION,
                              generator=FakeGenerator("x [a]"))
    assert coach_prompts.DEFAULT_PROFILE == BASELINE
    assert default.profile == BASELINE
    assert [m["role"] for m in default.messages] == ["system", "user"]


def test_specialized_only_adds_the_examples():
    sections = current_sections(MIDPOINT_QUESTION)
    baseline = coach.build_messages(MIDPOINT_QUESTION, sections, BASELINE)
    specialized = coach.build_messages(MIDPOINT_QUESTION, sections,
                                       SPECIALIZED)

    # Same system instructions and the same current turn.
    assert specialized[0] == baseline[0]
    assert specialized[-1] == baseline[-1]
    # In between: one user / assistant pair per few-shot example.
    examples = specialized[1:-1]
    assert len(examples) == 2 * len(FEW_SHOT_EXAMPLES)
    assert [m["role"] for m in examples] == (
        ["user", "assistant"] * len(FEW_SHOT_EXAMPLES)
    )
    for example, answer in zip(FEW_SHOT_EXAMPLES, examples[1::2]):
        assert answer["content"] == example["answer"]


def test_both_profiles_get_the_same_settings():
    baseline_fake = FakeGenerator("No [reliability-midpoint-not-required].")
    special_fake = FakeGenerator("No [reliability-midpoint-not-required].")

    coach.ask_coach(MIDPOINT_QUESTION, profile=BASELINE,
                    generator=baseline_fake)
    coach.ask_coach(MIDPOINT_QUESTION, profile=SPECIALIZED,
                    generator=special_fake)

    assert (baseline_fake.calls[0]["max_new_tokens"]
            == special_fake.calls[0]["max_new_tokens"])


def test_citation_copied_from_an_example_is_rejected():
    # rules-new-duel is a few-shot source, but not found for this question.
    current = {s.source_id for s in current_sections(MIDPOINT_QUESTION)}
    assert "rules-new-duel" not in current
    fake = FakeGenerator("No, it does not [rules-new-duel].")

    result = coach.ask_coach(MIDPOINT_QUESTION, profile=SPECIALIZED,
                             generator=fake)

    assert result.status == coach.VALIDATION_FAILED
    assert result.answer == fake.reply
    unknown = next(item for item in result.checks
                   if item["check"].startswith("every cited ID"))
    assert unknown["unknown_ids"] == ["rules-new-duel"]


def test_specialized_without_retrieval_is_rejected(capsys):
    with pytest.raises(ValueError, match="cannot be used with --no-retrieval"):
        coach.ask_coach(MIDPOINT_QUESTION, use_retrieval=False,
                        profile=SPECIALIZED, generator=FakeGenerator("x"))

    with pytest.raises(SystemExit) as stop:
        coach.main(["--question", MIDPOINT_QUESTION, "--no-retrieval",
                    "--profile", SPECIALIZED])
    assert stop.value.code == 2
    assert "cannot be used with --no-retrieval" in capsys.readouterr().err


def test_unknown_profile_is_rejected():
    with pytest.raises(ValueError, match="Unknown profile"):
        coach.ask_coach(MIDPOINT_QUESTION, profile="expert",
                        generator=FakeGenerator("x"))


def test_examples_use_their_own_knowledge_and_other_questions():
    index_ids = {s.source_id for s in coach_retrieval.default_index().sections}
    for example in FEW_SHOT_EXAMPLES:
        assert set(example["source_ids"]) <= index_ids
        cited = coach.find_citations(example["answer"])
        assert cited and set(cited) <= set(example["source_ids"])
        assert evaluate_coach.count_sentences(example["answer"]) <= 3
        assert example["question"] not in evaluate_coach.QUESTIONS


def test_comparison_searches_once_and_shares_the_sources():
    search_calls = []

    def counting_search(question, top_k):
        search_calls.append(question)
        return coach_retrieval.search(question, top_k)

    fake = FakeGenerator("An answer [not-a-real-source].")
    report = evaluate_coach.run_comparison(
        evaluate_coach.QUESTIONS[:2], generator=fake, search=counting_search
    )

    assert search_calls == list(evaluate_coach.QUESTIONS[:2])
    assert report["generations"] == 4 == len(fake.calls)
    for row in report["results"]:
        assert row["same_sources_for_both_profiles"]
        assert row["same_current_turn_for_both_profiles"]
        for profile in (BASELINE, SPECIALIZED):
            assert row["runs"][profile]["status"] == coach.VALIDATION_FAILED
    assert report["summary"][BASELINE]["validation_failed"] == 2


@pytest.mark.parametrize(
    "answer, words, sentences",
    [
        ("Yes [rules-win-and-draw]. It is a draw.", 5, 2),
        ("One. Two! Three? Four.", 4, 4),
        ("", 0, 0),
    ],
)
def test_word_and_sentence_counts(answer, words, sentences):
    assert evaluate_coach.count_words(answer) == words
    assert evaluate_coach.count_sentences(answer) == sentences
