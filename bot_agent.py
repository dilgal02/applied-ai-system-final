def choose_guess(low: int, high: int) -> int:
    """Pick the local opponent's next guess with a deterministic strategy.

    The bot always guesses the middle of the remaining range [low, high]
    (both inclusive). It only sees the range, never the secret number.

    Raises:
        ValueError: if low > high, because the range is empty.
    """
    if low > high:
        raise ValueError("Search interval is empty.")
    return (low + high) // 2


def update_bounds(
    low: int,
    high: int,
    guess: int,
    outcome: str,
) -> tuple[int, int]:
    """Narrow the search range [low, high] after the hint for a guess.

    outcome is "Too Low", "Too High" or "Win", the same names that
    logic_utils.check_guess returns. The secret number is never passed in.

    Raises:
        ValueError: if the range is empty, the guess is outside it,
            the outcome is unknown, or the hint leaves no numbers.
    """
    if low > high:
        raise ValueError("Search interval is empty.")
    if not low <= guess <= high:
        raise ValueError(f"Guess {guess} is outside the range {low}-{high}.")

    if outcome == "Too Low":
        new_low, new_high = guess + 1, high
    elif outcome == "Too High":
        new_low, new_high = low, guess - 1
    elif outcome == "Win":
        new_low, new_high = guess, guess
    else:
        raise ValueError(f"Unknown outcome: {outcome!r}.")

    if new_low > new_high:
        raise ValueError("Hint contradicts the remaining range.")
    return new_low, new_high
