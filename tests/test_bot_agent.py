import pytest

from bot_agent import choose_guess


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
