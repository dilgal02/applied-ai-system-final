from dataclasses import dataclass


@dataclass(frozen=True)
class DuelRound:
    """One finished round of the duel: the player's move and the bot's move.

    Each outcome is "Too Low", "Too High" or "Win", as returned by
    logic_utils.check_guess.
    """

    player_guess: int
    player_outcome: str
    bot_guess: int
    bot_outcome: str


@dataclass(frozen=True)
class DuelState:
    """The whole state of a duel between the player and the bot.

    low and high are the inclusive range of the game. player_secret is the
    player's number, which the bot tries to guess. bot_secret is the bot's
    number, which the player tries to guess. bot_low and bot_high are the
    range the bot still searches. Each entry in rounds holds both moves,
    so the number of used attempts is len(rounds).
    """

    low: int
    high: int
    attempt_limit: int
    player_secret: int
    bot_secret: int
    bot_low: int
    bot_high: int
    rounds: tuple[DuelRound, ...] = ()
    status: str = "playing"


def create_duel(
    low: int,
    high: int,
    attempt_limit: int,
    player_secret: int,
    bot_secret: int,
) -> DuelState:
    """Start a new duel with the given range, attempt limit and secrets.

    The bot starts by searching the whole range [low, high].

    Raises:
        ValueError: if a value is not an int, low > high,
            attempt_limit < 1, or a secret is outside [low, high].
    """
    values = {
        "low": low,
        "high": high,
        "attempt_limit": attempt_limit,
        "player_secret": player_secret,
        "bot_secret": bot_secret,
    }
    for name, value in values.items():
        # bool is a subclass of int, so True and False need their own check.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an int, got {value!r}.")

    if low > high:
        raise ValueError(f"low ({low}) is greater than high ({high}).")
    if attempt_limit < 1:
        raise ValueError(
            f"attempt_limit must be at least 1, got {attempt_limit}."
        )
    for name in ("player_secret", "bot_secret"):
        secret = values[name]
        if not low <= secret <= high:
            raise ValueError(
                f"{name} {secret} is outside the range {low}-{high}."
            )

    return DuelState(
        low=low,
        high=high,
        attempt_limit=attempt_limit,
        player_secret=player_secret,
        bot_secret=bot_secret,
        bot_low=low,
        bot_high=high,
        rounds=(),
        status="playing",
    )
