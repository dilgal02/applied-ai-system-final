from dataclasses import dataclass, replace

from bot_agent import choose_guess, update_bounds
from logic_utils import check_guess


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


def play_round(state: DuelState, player_guess: int) -> DuelState:
    """Play one round: the player's guess, then the bot's answer.

    Returns a new DuelState with the round added. The given state is
    never changed, also when an error is raised.

    Raises:
        ValueError: if the duel is over, no attempts are left, or
            player_guess is not an int inside [state.low, state.high].
    """
    if state.status != "playing":
        raise ValueError(f"The duel is already over: {state.status}.")
    if len(state.rounds) >= state.attempt_limit:
        raise ValueError(
            f"No attempts left: {len(state.rounds)} of "
            f"{state.attempt_limit} used."
        )
    if isinstance(player_guess, bool) or not isinstance(player_guess, int):
        raise ValueError(
            f"player_guess must be an int, got {player_guess!r}."
        )
    if not state.low <= player_guess <= state.high:
        raise ValueError(
            f"player_guess {player_guess} is outside the range "
            f"{state.low}-{state.high}."
        )

    # check_guess returns (outcome, message); only the outcome is needed.
    player_outcome, _ = check_guess(player_guess, state.bot_secret)

    # The bot only sees its own range, never the player's secret.
    bot_guess = choose_guess(state.bot_low, state.bot_high)
    bot_outcome, _ = check_guess(bot_guess, state.player_secret)
    bot_low, bot_high = update_bounds(
        state.bot_low, state.bot_high, bot_guess, bot_outcome
    )

    new_round = DuelRound(
        player_guess=player_guess,
        player_outcome=player_outcome,
        bot_guess=bot_guess,
        bot_outcome=bot_outcome,
    )
    new_rounds = state.rounds + (new_round,)

    player_won = player_outcome == "Win"
    bot_won = bot_outcome == "Win"
    if player_won and bot_won:
        status = "draw"
    elif player_won:
        status = "player_won"
    elif bot_won:
        status = "bot_won"
    elif len(new_rounds) >= state.attempt_limit:
        status = "draw"
    else:
        status = "playing"

    return replace(
        state,
        rounds=new_rounds,
        bot_low=bot_low,
        bot_high=bot_high,
        status=status,
    )
