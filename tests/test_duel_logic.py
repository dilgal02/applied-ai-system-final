import pytest

from duel_logic import create_duel


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
