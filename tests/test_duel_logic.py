from dataclasses import asdict

import pytest

from duel_logic import create_duel, play_round


def test_new_duel_keeps_settings_and_secrets():
    duel = create_duel(
        low=1,
        high=100,
        attempt_limit=8,
        player_secret=63,
        bot_secret=27,
    )
    assert duel.low == 1
    assert duel.high == 100
    assert duel.attempt_limit == 8
    assert duel.player_secret == 63
    assert duel.bot_secret == 27
    # The bot starts by searching the whole range.
    assert duel.bot_low == 1
    assert duel.bot_high == 100
    assert duel.rounds == ()
    assert duel.status == "playing"


def test_single_number_range_is_not_won_before_first_move():
    duel = create_duel(
        low=7,
        high=7,
        attempt_limit=1,
        player_secret=7,
        bot_secret=7,
    )
    assert duel.bot_low == 7
    assert duel.bot_high == 7
    assert duel.rounds == ()
    # Only one number is possible, but nobody has guessed yet.
    assert duel.status == "playing"


VALID_DUEL = {
    "low": 1,
    "high": 100,
    "attempt_limit": 8,
    "player_secret": 63,
    "bot_secret": 27,
}


@pytest.mark.parametrize(
    "change, message",
    [
        ({"low": 101}, "greater than high"),
        ({"attempt_limit": 0}, "at least 1"),
        ({"player_secret": 0}, "outside the range"),
        ({"player_secret": 101}, "outside the range"),
        ({"bot_secret": 0}, "outside the range"),
        ({"bot_secret": 101}, "outside the range"),
        ({"high": "100"}, "high must be an int"),
        ({"player_secret": 63.5}, "player_secret must be an int"),
        ({"attempt_limit": True}, "attempt_limit must be an int"),
    ],
    ids=[
        "low-above-high",
        "zero-attempts",
        "player-secret-below-range",
        "player-secret-above-range",
        "bot-secret-below-range",
        "bot-secret-above-range",
        "high-is-string",
        "player-secret-is-float",
        "attempt-limit-is-bool",
    ],
)
def test_create_duel_rejects_bad_arguments(change, message):
    # Start from valid arguments and break exactly one of them.
    with pytest.raises(ValueError, match=message):
        create_duel(**{**VALID_DUEL, **change})


def test_play_round_records_both_moves():
    state = create_duel(
        low=1,
        high=100,
        attempt_limit=8,
        player_secret=63,
        bot_secret=27,
    )
    snapshot = asdict(state)

    new_state = play_round(state, player_guess=40)

    # A new state is returned and the old one is untouched.
    assert new_state is not state
    assert asdict(state) == snapshot

    # Settings and both secrets are kept.
    assert new_state.low == 1
    assert new_state.high == 100
    assert new_state.attempt_limit == 8
    assert new_state.player_secret == 63
    assert new_state.bot_secret == 27

    assert len(new_state.rounds) == 1
    round_ = new_state.rounds[0]
    # Player: 40 against the bot's secret 27 is too high.
    assert round_.player_guess == 40
    assert round_.player_outcome == "Too High"
    # Bot: 50 (middle of 1-100) against the player's secret 63 is too low.
    assert round_.bot_guess == 50
    assert round_.bot_outcome == "Too Low"

    assert new_state.bot_low == 51
    assert new_state.bot_high == 100
    assert new_state.status == "playing"


@pytest.mark.parametrize(
    "player_secret, player_guess, player_outcome, bot_outcome, status",
    [
        (63, 27, "Win", "Too Low", "player_won"),
        (50, 40, "Too High", "Win", "bot_won"),
        (50, 27, "Win", "Win", "draw"),
        (63, 40, "Too High", "Too Low", "draw"),
    ],
    ids=[
        "player-wins",
        "bot-wins",
        "both-win-is-draw",
        "no-win-on-last-attempt-is-draw",
    ],
)
def test_play_round_ends_duel_on_last_attempt(
    player_secret, player_guess, player_outcome, bot_outcome, status
):
    # Only one attempt is allowed, so this single round ends the duel.
    state = create_duel(
        low=1,
        high=100,
        attempt_limit=1,
        player_secret=player_secret,
        bot_secret=27,
    )

    new_state = play_round(state, player_guess=player_guess)

    assert new_state.status == status
    assert len(new_state.rounds) == 1
    round_ = new_state.rounds[0]
    assert round_.player_guess == player_guess
    assert round_.player_outcome == player_outcome
    # The bot still answers, even after the player's correct guess.
    assert round_.bot_guess == 50
    assert round_.bot_outcome == bot_outcome


@pytest.mark.parametrize(
    "player_guess, message",
    [
        ("abc", "player_guess must be an int"),
        (40.5, "player_guess must be an int"),
        (True, "player_guess must be an int"),
        (0, "outside the range"),
        (101, "outside the range"),
    ],
    ids=[
        "text",
        "float",
        "bool",
        "below-range",
        "above-range",
    ],
)
def test_play_round_rejects_bad_guess(player_guess, message):
    state = create_duel(
        low=1,
        high=100,
        attempt_limit=8,
        player_secret=63,
        bot_secret=27,
    )
    snapshot = asdict(state)

    with pytest.raises(ValueError, match=message):
        play_round(state, player_guess=player_guess)

    # A bad guess adds no round and changes nothing in the game.
    assert asdict(state) == snapshot


@pytest.mark.parametrize(
    "player_secret, first_guess, status",
    [
        (63, 27, "player_won"),
        (50, 40, "bot_won"),
        (50, 27, "draw"),
    ],
    ids=[
        "player-won",
        "bot-won",
        "draw",
    ],
)
def test_play_round_rejects_moves_after_duel_is_over(
    player_secret, first_guess, status
):
    state = create_duel(
        low=1,
        high=100,
        attempt_limit=8,
        player_secret=player_secret,
        bot_secret=27,
    )
    finished = play_round(state, player_guess=first_guess)
    assert finished.status == status
    snapshot = asdict(finished)

    with pytest.raises(ValueError, match="already over"):
        play_round(finished, player_guess=1)

    # The finished duel stays exactly as it was.
    assert asdict(finished) == snapshot
