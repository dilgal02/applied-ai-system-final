"""Tests for the keyword search over the game's knowledge files."""
from pathlib import Path

import pytest

import coach_retrieval
from coach_retrieval import KnowledgeIndex, Section, load_index, search

ROOT = Path(__file__).resolve().parent.parent


def ids(results):
    return [result.section.source_id for result in results]


def flat(text):
    """The text on one line, so phrases split by line breaks still match."""
    return " ".join(text.split())


def test_simultaneous_win_finds_the_draw_rule():
    results = search("What happens if both players guess correctly?", 3)

    assert ids(results)[0] == "rules-win-and-draw"
    top = results[0].section
    assert top.path == "knowledge/rules.md"
    assert ("If both players guess correctly in the same round, the duel "
            "is a draw.") in flat(top.text)


def test_vector_strategy_inputs_are_found():
    results = search("What does Vector's strategy see?", 3)

    assert ids(results)[0] == "strategy-vector-inputs"
    text = flat(results[0].section.text)
    assert "choose_guess, receives only the low and high bounds" in text
    assert "Neither function ever receives your secret number." in text


def test_rejected_round_behavior_is_found():
    results = search("What happens when a round is rejected?", 3)

    assert ids(results)[0] == "reliability-rejected-round"
    assert results[0].section.path == "knowledge/reliability.md"
    assert ("When a round is rejected, the game state does not change."
            in flat(results[0].section.text))


@pytest.mark.parametrize(
    "query",
    [
        "Can I submit a fractional guess, and does it use a round?",
        "Can I submit decimal guesses?",
        "Can I enter a fraction as my guess?",
        "What happens if I enter 4.5 as my guess?",
    ],
    ids=["fractional-guess", "decimal-guesses", "fraction", "input-4-5"],
)
def test_fractional_input_questions_find_valid_guesses_first(query):
    results = search(query, 3)

    assert ids(results)[0] == "rules-valid-guesses"
    assert "a fraction such as 4.5" in flat(results[0].section.text)


def test_fraction_aliases_apply_after_stemming():
    for word in ("fraction", "fractions", "fractional", "decimal",
                 "decimals", "Decimals"):
        assert coach_retrieval.tokenize(word) == ["fraction"]
    # The knowledge files go through the same normalization.
    assert "fraction" in coach_retrieval.tokenize("a fraction such as 4.5")
    # No general rule that cuts "-al": "normal" stays a different word.
    assert coach_retrieval.tokenize("Normal") == ["normal"]


def test_decimal_regression_question_gets_the_rule_into_the_context():
    # "allowed" also matches "allows" in rules-difficulty-limits, so this
    # wording ranks the rule second. It is still among the found sources.
    results = search(
        "Are decimal guesses allowed, and will they consume a round?", 3
    )

    assert "rules-valid-guesses" in ids(results)


def test_hard_limit_question_finds_the_hard_sections():
    results = search("Can Vector run out of rounds on Hard?", 3)

    assert {"strategy-guesses-needed", "strategy-hard-limit"} <= set(
        ids(results)
    )


@pytest.mark.parametrize(
    "query",
    ["pizza recipe with tomatoes", "", "   ", "what is the"],
    ids=["unrelated", "empty", "spaces", "only-common-words"],
)
def test_no_match_gives_an_empty_list(query):
    assert search(query, 3) == []


def test_top_k_and_stable_order():
    query = "Vector range guess"
    many = search(query, 100)
    assert 3 < len(many) <= len(coach_retrieval.default_index().sections)
    # Best first; equal scores ordered by source_id.
    keys = [(-result.score, result.section.source_id) for result in many]
    assert keys == sorted(keys)
    assert all(result.score > 0 for result in many)

    assert search(query, 2) == many[:2]
    assert search(query, 1) == many[:1]
    assert search(query, 3) == search(query, 3)


def test_equal_scores_are_ordered_by_source_id():
    text = "Vector guesses the middle of its range."
    index = KnowledgeIndex([
        Section("zeta-copy", "a.md", "Same", text),
        Section("alpha-copy", "b.md", "Same", text),
        Section("other", "c.md", "Other", "Nothing about that here."),
    ])

    results = index.search("middle range", 5)

    assert ids(results) == ["alpha-copy", "zeta-copy"]
    assert results[0].score == results[1].score


@pytest.mark.parametrize("top_k", [0, -1, 1.5, True, "3", None])
def test_invalid_top_k_is_rejected(top_k):
    with pytest.raises(ValueError, match="top_k must be a whole number"):
        search("draw", top_k)


def test_every_section_text_matches_its_source_file():
    sections = coach_retrieval.default_index().sections
    assert len({section.source_id for section in sections}) == len(sections)
    for section in sections:
        content = (ROOT / section.path).read_text(encoding="utf-8")
        heading = f"## [{section.source_id}] {section.title}\n"
        assert heading in content
        # The stored text is exactly the text under that heading.
        after_heading = content.split(heading, 1)[1]
        assert after_heading.strip().startswith(section.text)


def test_duplicate_source_ids_are_rejected(tmp_path):
    (tmp_path / "one.md").write_text(
        "# One\n\n## [same-id] First\n\nSome text.\n", encoding="utf-8"
    )
    (tmp_path / "two.md").write_text(
        "# Two\n\n## [same-id] Second\n\nOther text.\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Duplicate source_id 'same-id'"):
        load_index(tmp_path)


def test_index_does_not_depend_on_the_working_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    index = load_index()

    assert index.sections == coach_retrieval.default_index().sections


def test_cli_prints_id_path_score_and_text(capsys):
    exit_code = coach_retrieval.main(
        ["--query", "What happens if both players guess correctly?",
         "--top-k", "1"]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "1. [rules-win-and-draw] Winning and draws" in output
    assert "source: knowledge/rules.md" in output
    assert "score:" in output
    assert "both players guess" in output
    assert "2. [" not in output
