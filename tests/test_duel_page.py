import copy
import random
import re
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import duel_logic
import duel_service

APP = str(Path(__file__).resolve().parent.parent / "app.py")
DUEL_PAGE = "pages/duel.py"
SOLO_PAGE = "pages/solo.py"
SOLO_KEYS = (
    "active_difficulty",
    "secret",
    "attempts",
    "score",
    "status",
    "history",
    "rounds",
)
GUARDRAIL_TEXT = "A safety check stopped this round"


def open_duel():
    at = AppTest.from_file(APP, default_timeout=20)
    at.run()
    at.switch_page(DUEL_PAGE).run()
    assert not at.exception
    return at


def button(at, label):
    return next(b for b in at.button if b.label == label)


def has_button(at, label):
    return any(b.label == label for b in at.button)


def start_duel(at, monkeypatch, difficulty, player_secret, bot_secret):
    at.selectbox(key="duel_difficulty_select").set_value(difficulty).run()
    secret_input = at.number_input(key=f"duel_secret_input_{difficulty}")
    secret_input.set_value(player_secret)
    # The opponent's number comes from random.randint; fix it for the test.
    with monkeypatch.context() as patch:
        patch.setattr(random, "randint", lambda low, high: bot_secret)
        button(at, "Start Duel").click().run()
    assert not at.exception
    return at.session_state["duel_state"]


def guess(at, value):
    played = len(at.session_state["duel_state"].rounds)
    at.text_input(key=f"duel_guess_input_{played}").input(value)
    button(at, "Submit Guess").click().run()


def duel_snapshot(at):
    return asdict(at.session_state["duel_state"])


def error_texts(at):
    return [element.value for element in at.error]


def visible_text(at):
    """All text the page shows, to check that no secret leaks."""
    parts = []
    for kind in (
        "title", "header", "subheader", "markdown", "caption",
        "info", "success", "warning", "error",
    ):
        parts += [element.value for element in getattr(at, kind)]
    parts += [f"{metric.label} {metric.value}" for metric in at.metric]
    parts += [table.value.to_string() for table in at.dataframe]
    text = "\n".join(parts)
    # The shared CSS is not text for the user, so only <style> is dropped.
    return re.sub(r"<style\b.*?</style>", "", text, flags=re.S | re.I)


def test_start_and_one_round(monkeypatch):
    at = open_duel()
    assert "duel_state" not in at.session_state
    assert has_button(at, "Start Duel")

    state = start_duel(at, monkeypatch, "Normal", player_secret=63,
                       bot_secret=27)
    assert (state.low, state.high, state.attempt_limit) == (1, 100, 8)
    assert (state.player_secret, state.bot_secret) == (63, 27)
    assert state.rounds == ()
    assert state.status == "playing"
    assert has_button(at, "Submit Guess")
    assert not has_button(at, "Start Duel")

    guess(at, "40")

    assert not at.exception
    state = at.session_state["duel_state"]
    assert len(state.rounds) == 1
    round_ = state.rounds[0]
    assert (round_.player_guess, round_.player_outcome) == (40, "Too High")
    assert (round_.bot_guess, round_.bot_outcome) == (50, "Too Low")
    assert (state.bot_low, state.bot_high) == (51, 100)
    assert state.status == "playing"

    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics == {"Rounds played": "1", "Rounds left": "7"}
    assert at.dataframe[0].value.to_dict("records") == [
        {
            "Round": 1,
            "Your guess": 40,
            "Your hint": "Too High",
            "Opponent's guess": 50,
            "Opponent's hint": "Too Low",
        }
    ]
    # The opponent's secret and the whole state are never shown.
    assert "27" not in visible_text(at)
    assert len(at.json) == 0


def test_rerun_does_not_repeat_round(monkeypatch):
    at = open_duel()
    start_duel(at, monkeypatch, "Normal", player_secret=63, bot_secret=27)
    guess(at, "40")
    saved = duel_snapshot(at)

    at.run()
    at.run()

    assert not at.exception
    assert duel_snapshot(at) == saved
    assert len(at.session_state["duel_state"].rounds) == 1


@pytest.mark.parametrize(
    "raw, message",
    [
        ("", "Enter a guess"),
        ("abc", "not a number"),
        ("4.5", "Fractions are not allowed"),
        ("0", "between 1 and 100"),
        ("101", "between 1 and 100"),
    ],
    ids=["empty", "text", "fraction", "below-range", "above-range"],
)
def test_bad_guess_keeps_duel(monkeypatch, raw, message):
    at = open_duel()
    start_duel(at, monkeypatch, "Normal", player_secret=63, bot_secret=27)
    guess(at, "40")
    saved = duel_snapshot(at)

    guess(at, raw)

    assert not at.exception
    assert any(message in text for text in error_texts(at))
    assert duel_snapshot(at) == saved
    # A plain rerun keeps both the duel and the message.
    at.run()
    assert duel_snapshot(at) == saved
    assert any(message in text for text in error_texts(at))


def test_guardrail_blocks_bad_engine_result(monkeypatch):
    at = open_duel()
    start_duel(at, monkeypatch, "Normal", player_secret=63, bot_secret=27)
    saved = duel_snapshot(at)
    real_play_round = duel_logic.play_round

    def broken_play_round(state, player_guess):
        # A faulty engine: a real round, but it claims the player won.
        candidate = real_play_round(state, player_guess)
        return replace(candidate, status="player_won")

    monkeypatch.setattr(duel_service, "play_round", broken_play_round)

    guess(at, "40")

    assert not at.exception
    errors = error_texts(at)
    assert any(GUARDRAIL_TEXT in text for text in errors)
    # Only the general message, not the inspector's inner reason.
    assert not any("expected" in text for text in errors)
    assert duel_snapshot(at) == saved
    assert has_button(at, "Submit Guess")


def test_simultaneous_win_is_draw_then_new_duel(monkeypatch):
    at = open_duel()
    # Hard is 1-50, so the bot's first guess is 25.
    start_duel(at, monkeypatch, "Hard", player_secret=25, bot_secret=10)

    guess(at, "10")

    assert not at.exception
    state = at.session_state["duel_state"]
    assert state.status == "draw"
    last = state.rounds[-1]
    assert (last.player_outcome, last.bot_outcome) == ("Win", "Win")
    assert any(
        "draw" in info.value and "both guessed right" in info.value
        for info in at.info
    )
    # No more moves after the end.
    assert not has_button(at, "Submit Guess")
    assert len(at.text_input) == 0

    button(at, "New Duel").click().run()

    assert not at.exception
    assert "duel_state" not in at.session_state
    assert has_button(at, "Start Duel")
    # The chosen difficulty stays, the old secret input is gone.
    assert at.selectbox(key="duel_difficulty_select").value == "Hard"
    assert at.number_input(key="duel_secret_input_Hard").value is None


def test_easy_duel_survives_solo_visit(monkeypatch):
    at = open_duel()
    # Easy is 1-20, so the bot's first guess is 10.
    start_duel(at, monkeypatch, "Easy", player_secret=7, bot_secret=15)
    guess(at, "12")
    saved = duel_snapshot(at)
    assert saved["status"] == "playing"
    assert len(saved["rounds"]) == 1

    at.switch_page(SOLO_PAGE).run()
    assert not at.exception
    at.switch_page(DUEL_PAGE).run()
    assert not at.exception

    assert duel_snapshot(at) == saved
    assert at.session_state["duel_difficulty"] == "Easy"
    assert has_button(at, "Submit Guess")
    assert not has_button(at, "Start Duel")


def test_new_duel_does_not_change_solo(monkeypatch):
    at = AppTest.from_file(APP, default_timeout=20)
    at.run()
    # One solo guess, so the solo game has real progress to protect.
    at.session_state["secret"] = 70
    at.text_input(key="guess_input_Normal").input("30")
    next(b for b in at.button if b.label.startswith("Submit Guess")).click()
    at.run()
    assert not at.exception
    solo = {key: copy.deepcopy(at.session_state[key]) for key in SOLO_KEYS}
    assert solo["attempts"] == 1

    at.switch_page(DUEL_PAGE).run()
    start_duel(at, monkeypatch, "Hard", player_secret=25, bot_secret=10)
    guess(at, "10")
    button(at, "New Duel").click().run()
    assert not at.exception
    assert {key: at.session_state[key] for key in SOLO_KEYS} == solo

    at.switch_page(SOLO_PAGE).run()
    assert not at.exception
    assert {key: at.session_state[key] for key in SOLO_KEYS} == solo


def test_new_duel_during_play_returns_to_setup(monkeypatch):
    at = AppTest.from_file(APP, default_timeout=20)
    at.run()
    # One solo guess, so the solo game has real progress to protect.
    at.session_state["secret"] = 70
    at.text_input(key="guess_input_Normal").input("30")
    next(b for b in at.button if b.label.startswith("Submit Guess")).click()
    at.run()
    assert not at.exception
    solo = {key: copy.deepcopy(at.session_state[key]) for key in SOLO_KEYS}

    at.switch_page(DUEL_PAGE).run()
    # Hard is 1-50: Vector guesses 25 (too low for 40), the player's 20
    # is too high for 10, so the duel goes on.
    start_duel(at, monkeypatch, "Hard", player_secret=40, bot_secret=10)
    guess(at, "20")
    assert at.session_state["duel_state"].status == "playing"
    assert len(at.dataframe) == 1
    # New Duel is there during the duel, as one button.
    assert [b.label for b in at.button].count("New Duel") == 1
    # Something typed but not sent yet must not survive New Duel.
    at.text_input(key="duel_guess_input_1").input("33")

    button(at, "New Duel").click().run()

    assert not at.exception
    assert "duel_state" not in at.session_state
    assert has_button(at, "Start Duel")
    assert not has_button(at, "Submit Guess")
    assert len(at.dataframe) == 0
    assert at.selectbox(key="duel_difficulty_select").value == "Hard"
    assert at.number_input(key="duel_secret_input_Hard").value is None
    assert "duel_guess_input_1" not in at.session_state
    assert {key: at.session_state[key] for key in SOLO_KEYS} == solo

    at.switch_page(SOLO_PAGE).run()
    assert not at.exception
    assert {key: at.session_state[key] for key in SOLO_KEYS} == solo
