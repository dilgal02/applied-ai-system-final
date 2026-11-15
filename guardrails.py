from duel_logic import DuelRound, DuelState

# Settings and secrets that a round must never change.
KEPT_FIELDS = ("low", "high", "attempt_limit", "player_secret", "bot_secret")

# Numbers in before that must be real ints before they are compared.
BEFORE_INT_FIELDS = (
    "low",
    "high",
    "player_secret",
    "bot_secret",
    "bot_low",
    "bot_high",
)


def _is_int(value) -> bool:
    """Return True for an int. A bool does not count as an int here."""
    return isinstance(value, int) and not isinstance(value, bool)


def _expected_outcome(guess: int, secret: int) -> str:
    """Work out the hint for a guess with plain number comparisons."""
    if guess < secret:
        return "Too Low"
    if guess > secret:
        return "Too High"
    return "Win"


def validate_transition(before: DuelState, after: DuelState) -> None:
    """Check one duel step from before to after.

    Structure:
    - both values are DuelState objects;
    - rounds in both states is a tuple of DuelRound objects;
    - before.attempt_limit is a positive int (not a bool);
    - before was still playing and had attempts left;
    - settings and secrets kept the same value and type;
    - exactly one round was added and earlier rounds are unchanged.

    Guesses and hints (worked out here, without the game functions):
    - the numbers in before are ints (not bools);
    - the game range is not empty and holds both secrets;
    - in every round both guesses are ints inside [low, high];
    - player_outcome matches player_guess against bot_secret, and
      bot_outcome matches bot_guess against player_secret;
    - the bot's new guess is inside its range [bot_low, bot_high].

    Bot range and result (rebuilt here from the whole history):
    - the bot's range starts at [low, high]; every bot guess must be
      inside the range rebuilt so far, and the range must stay non-empty
      and keep holding player_secret;
    - the range rebuilt from the earlier rounds equals before.bot_low
      and before.bot_high;
    - the final rebuilt range equals after.bot_low and after.bot_high,
      which must be ints (not bools);
    - no round follows a round that ended the duel, and after.status
      is a str equal to the status rebuilt from the history.

    Returns None when everything is fine. Neither state is changed.

    Raises:
        ValueError: with a message that names the broken rule and,
            where it applies, the round number (starting at 1).
    """
    for name, state in (("before", before), ("after", after)):
        if not isinstance(state, DuelState):
            raise ValueError(
                f"{name} must be a DuelState, got {type(state).__name__}."
            )
        if not isinstance(state.rounds, tuple):
            raise ValueError(
                f"{name}.rounds must be a tuple, "
                f"got {type(state.rounds).__name__}."
            )
        for index, round_ in enumerate(state.rounds):
            if not isinstance(round_, DuelRound):
                raise ValueError(
                    f"{name}.rounds[{index}] must be a DuelRound, "
                    f"got {type(round_).__name__}."
                )

    limit = before.attempt_limit
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError(
            f"before.attempt_limit must be a positive int, got {limit!r}."
        )
    if before.status != "playing":
        raise ValueError(
            f"before.status must be 'playing', got {before.status!r}."
        )
    if len(before.rounds) >= limit:
        raise ValueError(
            f"before has no attempts left: {len(before.rounds)} of "
            f"{limit} used."
        )

    for field in KEPT_FIELDS:
        old = getattr(before, field)
        new = getattr(after, field)
        if type(old) is not type(new) or old != new:
            raise ValueError(f"{field} changed: {old!r} -> {new!r}.")

    if len(after.rounds) != len(before.rounds) + 1:
        raise ValueError(
            f"Expected exactly one new round: before has "
            f"{len(before.rounds)}, after has {len(after.rounds)}."
        )
    if after.rounds[:-1] != before.rounds:
        raise ValueError("Earlier rounds were changed.")

    for field in BEFORE_INT_FIELDS:
        value = getattr(before, field)
        if not _is_int(value):
            raise ValueError(f"before.{field} must be an int, got {value!r}.")

    if before.low > before.high:
        raise ValueError(
            f"Game range is empty: low {before.low} > high {before.high}."
        )
    for field in ("player_secret", "bot_secret"):
        secret = getattr(before, field)
        if not before.low <= secret <= before.high:
            raise ValueError(
                f"{field} {secret} is outside the range "
                f"{before.low}-{before.high}."
            )

    for number, round_ in enumerate(after.rounds, start=1):
        # The player guesses the bot's secret; the bot guesses the player's.
        moves = (
            ("player", round_.player_guess, round_.player_outcome,
             before.bot_secret),
            ("bot", round_.bot_guess, round_.bot_outcome,
             before.player_secret),
        )
        for side, guess, _, _ in moves:
            if not _is_int(guess):
                raise ValueError(
                    f"Round {number}: {side}_guess must be an int, "
                    f"got {guess!r}."
                )
            if not before.low <= guess <= before.high:
                raise ValueError(
                    f"Round {number}: {side}_guess {guess} is outside "
                    f"the range {before.low}-{before.high}."
                )
        for side, guess, outcome, secret in moves:
            if not isinstance(outcome, str):
                raise ValueError(
                    f"Round {number}: {side}_outcome must be a str, "
                    f"got {outcome!r}."
                )
            expected = _expected_outcome(guess, secret)
            if outcome != expected:
                raise ValueError(
                    f"Round {number}: {side}_outcome is {outcome!r}, "
                    f"expected {expected!r}."
                )

    new_round = after.rounds[-1]
    if not before.bot_low <= new_round.bot_guess <= before.bot_high:
        raise ValueError(
            f"Round {len(after.rounds)}: bot_guess {new_round.bot_guess} "
            f"is outside the bot's range "
            f"{before.bot_low}-{before.bot_high}."
        )

    # Rebuild the bot's range and the duel status from the whole history.
    bot_low, bot_high = before.low, before.high
    status = "playing"
    for number, round_ in enumerate(after.rounds, start=1):
        if number == len(after.rounds):
            # Before the new round: the earlier rounds must lead to the
            # range stored in before (with no history, that is low-high).
            if (bot_low, bot_high) != (before.bot_low, before.bot_high):
                raise ValueError(
                    f"before bot range {before.bot_low}-{before.bot_high} "
                    f"does not match the range rebuilt from history "
                    f"({bot_low}-{bot_high})."
                )
        if status != "playing":
            raise ValueError(
                f"Round {number}: the duel was already over after round "
                f"{number - 1} ({status})."
            )

        guess = round_.bot_guess
        if not bot_low <= guess <= bot_high:
            raise ValueError(
                f"Round {number}: bot_guess {guess} is not in the bot's "
                f"rebuilt range {bot_low}-{bot_high}."
            )
        if round_.bot_outcome == "Too Low":
            bot_low = guess + 1
        elif round_.bot_outcome == "Too High":
            bot_high = guess - 1
        else:  # "Win": the hint checks above allow no other value.
            bot_low = bot_high = guess
        if bot_low > bot_high:
            raise ValueError(
                f"Round {number}: the bot's rebuilt range is empty "
                f"({bot_low}-{bot_high})."
            )
        if not bot_low <= before.player_secret <= bot_high:
            raise ValueError(
                f"Round {number}: the bot's rebuilt range "
                f"{bot_low}-{bot_high} no longer holds player_secret."
            )

        player_won = round_.player_outcome == "Win"
        bot_won = round_.bot_outcome == "Win"
        if player_won and bot_won:
            status = "draw"
        elif player_won:
            status = "player_won"
        elif bot_won:
            status = "bot_won"
        elif number >= before.attempt_limit:
            status = "draw"
        else:
            status = "playing"

    for field in ("bot_low", "bot_high"):
        value = getattr(after, field)
        if not _is_int(value):
            raise ValueError(f"after.{field} must be an int, got {value!r}.")
    if (bot_low, bot_high) != (after.bot_low, after.bot_high):
        raise ValueError(
            f"after bot range {after.bot_low}-{after.bot_high} does not "
            f"match the range rebuilt from history ({bot_low}-{bot_high})."
        )

    if not isinstance(after.status, str):
        raise ValueError(
            f"after.status must be a str, got {after.status!r}."
        )
    if after.status != status:
        raise ValueError(
            f"after.status is {after.status!r}, expected {status!r}."
        )
