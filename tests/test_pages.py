import copy
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")

GAME_KEYS = (
    "active_difficulty",
    "secret",
    "attempts",
    "score",
    "status",
    "history",
    "rounds",
)


def open_app():
    at = AppTest.from_file(APP, default_timeout=20)
    at.run()
    return at


def titles(at):
    return [title.value for title in at.title]


def game_snapshot(at):
    return {key: copy.deepcopy(at.session_state[key]) for key in GAME_KEYS}


def test_app_opens_solo_game():
    at = open_app()

    assert not at.exception
    assert titles(at) == ["Solo Game"]
    assert at.text_input(key="guess_input_Normal").label == "Enter your guess:"


def test_duel_is_a_separate_page():
    at = open_app()

    at.switch_page("pages/duel.py").run()

    assert not at.exception
    assert titles(at) == ["Number Duel"]
    # The duel has its own settings and setup form.
    assert at.selectbox(key="duel_difficulty_select").value == "Normal"
    secret_input = at.number_input(key="duel_secret_input_Normal")
    assert secret_input.label == "Your secret number"
    assert any(b.label == "Start Duel" for b in at.button)
    # Nothing from the solo game is on this page.
    assert len(at.sidebar.selectbox) == 0
    assert len(at.text_input) == 0
    assert not any(b.label.startswith("Submit Guess") for b in at.button)
    assert not any(b.label.startswith("New Game") for b in at.button)


def test_solo_game_survives_a_visit_to_duel():
    at = open_app()
    at.sidebar.selectbox(key="solo_difficulty").set_value("Easy").run()
    at.session_state["secret"] = 10
    at.text_input(key="guess_input_Easy").input("5")
    next(b for b in at.button if b.label.startswith("Submit Guess")).click()
    at.run()
    assert not at.exception
    saved = game_snapshot(at)
    assert saved["active_difficulty"] == "Easy"
    assert saved["secret"] == 10
    assert saved["attempts"] == 1
    assert saved["history"] == [5]

    at.switch_page("pages/duel.py").run()
    assert not at.exception
    at.switch_page("pages/solo.py").run()
    assert not at.exception

    assert titles(at) == ["Solo Game"]
    assert at.sidebar.selectbox(key="solo_difficulty").value == "Easy"
    assert game_snapshot(at) == saved
