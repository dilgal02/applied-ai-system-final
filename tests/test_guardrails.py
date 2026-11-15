from dataclasses import asdict, replace

import pytest

from duel_logic import create_duel, play_round
from guardrails import validate_transition


@pytest.mark.parametrize(
    "previous_guesses, new_guess",
    [
        ((), 40),
        ((40,), 20),
    ],
    ids=[
        "first-round",
        "second-round-with-history",
    ],
)
def test_valid_transition_passes(previous_guesses, new_guess):
    before = create_duel(
        low=1,
        high=100,
        attempt_limit=8,
        player_secret=63,
        bot_secret=27,
    )
    for guess in previous_guesses:
        before = play_round(before, player_guess=guess)

    after = play_round(before, player_guess=new_guess)
    before_snapshot = asdict(before)
    after_snapshot = asdict(after)

    assert validate_transition(before, after) is None

    # The check only reads the states and never changes them.
    assert asdict(before) == before_snapshot
    assert asdict(after) == after_snapshot


@pytest.mark.parametrize(
    "change, message",
    [
        ({"low": 0}, "low changed"),
        ({"high": 99}, "high changed"),
        ({"attempt_limit": 9}, "attempt_limit changed"),
        ({"player_secret": 64}, "player_secret changed"),
        ({"bot_secret": 28}, "bot_secret changed"),
        # Same number, different type: 63.0 == 63 and True == 1.
        ({"player_secret": 63.0}, "player_secret changed"),
        ({"low": True}, "low changed"),
    ],
    ids=[
        "low-value",
        "high-value",
        "attempt-limit-value",
        "player-secret-value",
        "bot-secret-value",
        "player-secret-float",
        "low-bool",
    ],
)
def test_changed_setting_or_secret_is_rejected(change, message):
    before = create_duel(
        low=1,
        high=100,
        attempt_limit=8,
        player_secret=63,
        bot_secret=27,
    )
    after = play_round(before, player_guess=40)
    # Break exactly one setting or secret in an otherwise valid step.
    bad_after = replace(after, **change)
    before_snapshot = asdict(before)
    bad_after_snapshot = asdict(bad_after)

    with pytest.raises(ValueError, match=message):
        validate_transition(before, bad_after)

    assert asdict(before) == before_snapshot
    assert asdict(bad_after) == bad_after_snapshot


def drop_new_round(before, after):
    return replace(after, rounds=before.rounds)


def add_extra_round(before, after):
    return replace(after, rounds=after.rounds + (after.rounds[-1],))


def change_first_guess(before, after):
    first = replace(after.rounds[0], player_guess=39)
    return replace(after, rounds=(first,) + after.rounds[1:])


@pytest.mark.parametrize(
    "break_history, message",
    [
        (drop_new_round, "Expected exactly one new round"),
        (add_extra_round, "Expected exactly one new round"),
        (change_first_guess, "Earlier rounds were changed"),
    ],
    ids=[
        "new-round-missing",
        "extra-round-added",
        "earlier-guess-changed",
    ],
)
def test_broken_history_is_rejected(break_history, message):
    duel = create_duel(
        low=1,
        high=100,
        attempt_limit=8,
        player_secret=63,
        bot_secret=27,
    )
    before = play_round(duel, player_guess=40)
    after = play_round(before, player_guess=20)
    bad_after = break_history(before, after)
    before_snapshot = asdict(before)
    bad_after_snapshot = asdict(bad_after)

    with pytest.raises(ValueError, match=message):
        validate_transition(before, bad_after)

    assert asdict(before) == before_snapshot
    assert asdict(bad_after) == bad_after_snapshot


@pytest.mark.parametrize(
    "status_override, message",
    [
        (None, "before.status must be 'playing'"),
        ("playing", "before has no attempts left"),
    ],
    ids=[
        "duel-is-over",
        "playing-but-no-attempts-left",
    ],
)
def test_round_after_finished_duel_is_rejected(status_override, message):
    duel = create_duel(
        low=1,
        high=100,
        attempt_limit=1,
        player_secret=63,
        bot_secret=27,
    )
    # One attempt, no win: the duel ends in a draw after this round.
    before = play_round(duel, player_guess=40)
    assert before.status == "draw"
    assert len(before.rounds) == 1
    if status_override is not None:
        # Fake status, but the only attempt is still used.
        before = replace(before, status=status_override)

    # A faulty component tries to add one more round.
    after = replace(before, rounds=before.rounds + (before.rounds[-1],))
    before_snapshot = asdict(before)
    after_snapshot = asdict(after)

    with pytest.raises(ValueError, match=message):
        validate_transition(before, after)

    assert asdict(before) == before_snapshot
    assert asdict(after) == after_snapshot
