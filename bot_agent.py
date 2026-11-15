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
