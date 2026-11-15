import pytest

from bot_agent import choose_guess, update_bounds


def test_full_range_guesses_middle():
    # Range 1 to 100: the bot starts in the middle.
    assert choose_guess(1, 100) == 50


def test_narrowed_range_guesses_middle():
    # After "Go HIGHER" on 50 the range is 51 to 100.
    assert choose_guess(51, 100) == 75


def test_single_candidate_is_guessed():
    # Only one number is left, so the bot must guess it.
    assert choose_guess(7, 7) == 7


def test_empty_range_raises_error():
    # low > high means no number is left to guess.
    with pytest.raises(ValueError, match="Search interval is empty."):
        choose_guess(10, 5)


def test_too_low_moves_low_bound_up():
    # "Go HIGHER" on 50: the secret is above 50.
    assert update_bounds(1, 100, 50, "Too Low") == (51, 100)


def test_too_high_moves_high_bound_down():
    # "Go LOWER" on 75: the secret is below 75.
    assert update_bounds(51, 100, 75, "Too High") == (51, 74)


def test_win_leaves_only_the_guess():
    # A correct guess leaves just that number.
    assert update_bounds(51, 74, 63, "Win") == (63, 63)


@pytest.mark.parametrize(
    "low, high, guess, outcome, message",
    [
        (10, 5, 7, "Too Low", "Search interval is empty"),
        (1, 100, 0, "Too Low", "outside the range"),
        (1, 100, 101, "Too High", "outside the range"),
        (1, 100, 50, "Too Big", "Unknown outcome"),
        (1, 100, 100, "Too Low", "Hint contradicts the remaining range"),
        (1, 100, 1, "Too High", "Hint contradicts the remaining range"),
    ],
    ids=[
        "empty-range",
        "guess-below-range",
        "guess-above-range",
        "unknown-outcome",
        "too-low-on-high-bound",
        "too-high-on-low-bound",
    ],
)
def test_update_bounds_rejects_bad_input(low, high, guess, outcome, message):
    # Each bad input raises ValueError with a clear message.
    with pytest.raises(ValueError, match=message):
        update_bounds(low, high, guess, outcome)
