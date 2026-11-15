from dataclasses import asdict, replace

import pytest

from duel_logic import DuelRound, create_duel, play_round
from guardrails import validate_transition


@pytest.mark.parametrize(
    "player_secret, previous_guesses, new_guess, expected_status",
    [
        (63, (), 40, "playing"),
        (63, (40,), 20, "playing"),
        (63, (), 27, "player_won"),
        (50, (), 40, "bot_won"),
        (50, (), 27, "draw"),
    ],
    ids=[
        "first-round",
        "second-round-with-history",
        "player-won",
        "bot-won",
        "draw",
    ],
)
def test_valid_transition_passes(
    player_secret, previous_guesses, new_guess, expected_status
):
    before = create_duel(
        low=1,
        high=100,
        attempt_limit=8,
        player_secret=player_secret,
        bot_secret=27,
    )
    for guess in previous_guesses:
        before = play_round(before, player_guess=guess)

    after = play_round(before, player_guess=new_guess)
    assert after.status == expected_status
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


@pytest.mark.parametrize(
    "change, message",
    [
        ({"player_outcome": "Too Low"}, "player_outcome"),
        ({"bot_outcome": "Too High"}, "bot_outcome"),
        ({"player_outcome": "Win"}, "player_outcome"),
        ({"bot_outcome": "Win"}, "bot_outcome"),
        ({"player_outcome": "Too Big"}, "player_outcome"),
        ({"bot_outcome": None}, "bot_outcome must be a str"),
    ],
    ids=[
        "player-too-low",
        "bot-too-high",
        "player-fake-win",
        "bot-fake-win",
        "player-unknown-outcome",
        "bot-outcome-none",
    ],
)
def test_wrong_outcome_is_rejected(change, message):
    before = create_duel(
        low=1,
        high=100,
        attempt_limit=8,
        player_secret=63,
        bot_secret=27,
    )
    after = play_round(before, player_guess=40)
    # Correct hints: 40 vs 27 is "Too High", 50 vs 63 is "Too Low".
    assert after.rounds[-1].player_outcome == "Too High"
    assert after.rounds[-1].bot_outcome == "Too Low"

    # Spoil one outcome of the last round and keep everything else.
    bad_round = replace(after.rounds[-1], **change)
    bad_after = replace(after, rounds=after.rounds[:-1] + (bad_round,))
    before_snapshot = asdict(before)
    bad_after_snapshot = asdict(bad_after)

    with pytest.raises(ValueError, match=message):
        validate_transition(before, bad_after)

    assert asdict(before) == before_snapshot
    assert asdict(bad_after) == bad_after_snapshot


@pytest.mark.parametrize(
    "index, field, value, message",
    [
        (1, "player_guess", "abc", "Round 2: player_guess must be an int"),
        (1, "player_guess", True, "Round 2: player_guess must be an int"),
        (1, "bot_guess", 75.0, "Round 2: bot_guess must be an int"),
        (0, "player_guess", 40.0, "Round 1: player_guess must be an int"),
    ],
    ids=[
        "new-round-player-text",
        "new-round-player-bool",
        "new-round-bot-float",
        "old-round-player-float",
    ],
)
def test_guess_with_wrong_type_is_rejected(index, field, value, message):
    duel = create_duel(
        low=1,
        high=100,
        attempt_limit=8,
        player_secret=63,
        bot_secret=27,
    )
    before = play_round(duel, player_guess=40)
    after = play_round(before, player_guess=20)

    # Replace one guess in one round and keep all other rounds and fields.
    bad_round = replace(after.rounds[index], **{field: value})
    bad_rounds = (
        after.rounds[:index] + (bad_round,) + after.rounds[index + 1:]
    )
    bad_after = replace(after, rounds=bad_rounds)

    # The history check alone does not catch 40.0, because 40.0 == 40.
    assert bad_after.rounds[:-1] == before.rounds
    before_snapshot = asdict(before)
    bad_after_snapshot = asdict(bad_after)

    with pytest.raises(ValueError, match=message):
        validate_transition(before, bad_after)

    assert asdict(before) == before_snapshot
    assert asdict(bad_after) == bad_after_snapshot


@pytest.mark.parametrize(
    "side, guess, outcome, message",
    [
        ("player", 0, "Too Low", "player_guess 0 is outside the range"),
        ("player", 101, "Too High", "player_guess 101 is outside the range"),
        ("bot", 0, "Too Low", "bot_guess 0 is outside the range"),
        ("bot", 101, "Too High", "bot_guess 101 is outside the range"),
        ("bot", 50, "Too Low", "outside the bot's range"),
    ],
    ids=[
        "player-below-game-range",
        "player-above-game-range",
        "bot-below-game-range",
        "bot-above-game-range",
        "bot-outside-own-range",
    ],
)
def test_guess_outside_range_is_rejected(side, guess, outcome, message):
    duel = create_duel(
        low=1,
        high=100,
        attempt_limit=8,
        player_secret=63,
        bot_secret=27,
    )
    before = play_round(duel, player_guess=40)
    # After "Too Low" on 50 the bot only searches 51-100.
    assert before.bot_low == 51
    assert before.bot_high == 100
    after = play_round(before, player_guess=20)

    # Change one side's guess together with a hint that fits it,
    # so only the range rule is broken.
    bad_round = replace(
        after.rounds[-1],
        **{f"{side}_guess": guess, f"{side}_outcome": outcome},
    )
    bad_after = replace(after, rounds=after.rounds[:-1] + (bad_round,))
    before_snapshot = asdict(before)
    bad_after_snapshot = asdict(bad_after)

    with pytest.raises(ValueError, match=message):
        validate_transition(before, bad_after)

    assert asdict(before) == before_snapshot
    assert asdict(bad_after) == bad_after_snapshot


# --- Bot range and duel result ---------------------------------------

DUEL = {
    "low": 1,
    "high": 100,
    "attempt_limit": 8,
    "player_secret": 63,
    "bot_secret": 27,
}


def make_duel(**changes):
    return create_duel(**{**DUEL, **changes})


def two_rounds():
    """before: bot guessed 50 ("Too Low"), range 51-100.
    after: bot guessed 75 ("Too High"), range 51-74, still playing."""
    before = play_round(make_duel(), player_guess=40)
    after = play_round(before, player_guess=20)
    return before, after


def assert_rejected(before, after, message):
    """validate_transition must fail with message and change nothing."""
    before_snapshot = asdict(before)
    after_snapshot = asdict(after)

    with pytest.raises(ValueError, match=message):
        validate_transition(before, after)

    assert asdict(before) == before_snapshot
    assert asdict(after) == after_snapshot


@pytest.mark.parametrize(
    "duel_changes, previous_guesses, new_guess, outcomes, status",
    [
        (
            {"low": 7, "high": 7, "attempt_limit": 1,
             "player_secret": 7, "bot_secret": 7},
            (), 7, ("Win", "Win"), "draw",
        ),
        ({"attempt_limit": 2}, (40,), 20, ("Too Low", "Too High"), "draw"),
    ],
    ids=[
        "single-number-both-win",
        "last-attempt-without-winner",
    ],
)
def test_valid_final_transition_passes(
    duel_changes, previous_guesses, new_guess, outcomes, status
):
    before = make_duel(**duel_changes)
    for guess in previous_guesses:
        before = play_round(before, player_guess=guess)
    after = play_round(before, player_guess=new_guess)
    last = after.rounds[-1]
    assert (last.player_outcome, last.bot_outcome) == outcomes
    assert after.status == status
    before_snapshot = asdict(before)
    after_snapshot = asdict(after)

    assert validate_transition(before, after) is None

    assert asdict(before) == before_snapshot
    assert asdict(after) == after_snapshot


@pytest.mark.parametrize(
    "change",
    [
        {"bot_high": 75},
        {"bot_low": 52},
        {"bot_low": 51, "bot_high": 100},
    ],
    ids=[
        "high-keeps-ruled-out-guess",
        "low-moved-too-far",
        "hint-not-applied",
    ],
)
def test_wrong_new_bot_range_is_rejected(change):
    before, after = two_rounds()
    assert (after.bot_low, after.bot_high) == (51, 74)
    assert_rejected(before, replace(after, **change), "after bot range")


@pytest.mark.parametrize(
    "field, value",
    [
        ("bot_low", 51.0),
        ("bot_high", 74.0),
    ],
    ids=[
        "low-float",
        "high-float",
    ],
)
def test_float_bot_bound_is_rejected(field, value):
    before, after = two_rounds()
    bad_after = replace(after, **{field: value})
    # The number is equal, so only the type check can catch it.
    assert getattr(bad_after, field) == getattr(after, field)
    assert_rejected(before, bad_after, f"after.{field} must be an int")


@pytest.mark.parametrize(
    "previous_guesses, fake_range",
    [
        ((), {"bot_low": 2}),
        ((40,), {"bot_low": 1, "bot_high": 100}),
    ],
    ids=[
        "no-history-but-not-full-range",
        "earlier-hint-ignored",
    ],
)
def test_before_bot_range_must_match_history(previous_guesses, fake_range):
    before = make_duel()
    for guess in previous_guesses:
        before = play_round(before, player_guess=guess)
    fake_before = replace(before, **fake_range)
    # play_round trusts the fake range, so after is consistent with it.
    after = play_round(fake_before, player_guess=20)
    assert_rejected(fake_before, after, "before bot range")


@pytest.mark.parametrize(
    "fake_status",
    ["player_won", "draw"],
)
def test_premature_end_is_rejected(fake_status):
    before, after = two_rounds()
    assert after.status == "playing"
    bad_after = replace(after, status=fake_status)
    assert_rejected(before, bad_after, "expected 'playing'")


@pytest.mark.parametrize(
    "player_secret, guess, real_status",
    [
        (63, 27, "player_won"),
        (50, 40, "bot_won"),
        (50, 27, "draw"),
    ],
    ids=[
        "player-won",
        "bot-won",
        "both-won",
    ],
)
def test_playing_after_real_win_is_rejected(player_secret, guess, real_status):
    before = make_duel(player_secret=player_secret)
    after = play_round(before, player_guess=guess)
    assert after.status == real_status
    bad_after = replace(after, status="playing")
    assert_rejected(before, bad_after, f"expected '{real_status}'")


@pytest.mark.parametrize(
    "player_secret, winning_guess, real_status",
    [
        (63, 27, "player_won"),
        (50, 40, "bot_won"),
    ],
    ids=[
        "after-player-won",
        "after-bot-won",
    ],
)
def test_round_after_earlier_win_is_rejected(
    player_secret, winning_guess, real_status
):
    finished = play_round(
        make_duel(player_secret=player_secret), player_guess=winning_guess
    )
    assert finished.status == real_status
    # A faulty component resets the status and plays one more round.
    fake_before = replace(finished, status="playing")
    after = play_round(fake_before, player_guess=20)
    assert_rejected(fake_before, after, "already over")


def empty_game_range():
    before = make_duel()
    after = play_round(before, player_guess=40)
    return replace(before, low=10, high=5), replace(after, low=10, high=5)


def secret_outside_game_range():
    before = make_duel()
    after = play_round(before, player_guess=40)
    return (
        replace(before, player_secret=101),
        replace(after, player_secret=101),
    )


def earlier_bot_guess_outside_rebuilt_range():
    first = play_round(make_duel(), player_guess=40)
    # After round 1 the bot searches 51-100, but round 2 claims 30.
    # The hint "Too Low" (30 vs 63) is correct, only the range is wrong.
    bad_round = DuelRound(
        player_guess=20,
        player_outcome="Too Low",
        bot_guess=30,
        bot_outcome="Too Low",
    )
    before = replace(
        first, rounds=first.rounds + (bad_round,), bot_low=31, bot_high=100
    )
    after = play_round(before, player_guess=10)
    return before, after


@pytest.mark.parametrize(
    "build, message",
    [
        (empty_game_range, "Game range is empty"),
        (secret_outside_game_range, "player_secret 101 is outside the range"),
        (
            earlier_bot_guess_outside_rebuilt_range,
            "Round 2: bot_guess 30 is not in the bot's rebuilt range",
        ),
    ],
    ids=[
        "empty-game-range",
        "secret-outside-game-range",
        "earlier-bot-guess-outside-rebuilt-range",
    ],
)
def test_bad_setup_or_history_is_rejected(build, message):
    before, after = build()
    assert_rejected(before, after, message)
