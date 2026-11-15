from duel_logic import DuelRound, DuelState

# Settings and secrets that a round must never change.
KEPT_FIELDS = ("low", "high", "attempt_limit", "player_secret", "bot_secret")


def validate_transition(before: DuelState, after: DuelState) -> None:
    """Check the structure of one duel step from before to after.

    This is a structural check only. It makes sure that:
    - both values are DuelState objects;
    - rounds in both states is a tuple of DuelRound objects;
    - before.attempt_limit is a positive int (not a bool);
    - before was still playing and had attempts left;
    - settings and secrets kept the same value and type;
    - exactly one round was added and earlier rounds are unchanged.

    It does not check whether the guesses, hints, the bot's new range
    or the new status are correct.

    Returns None when everything is fine. Neither state is changed.

    Raises:
        ValueError: with a message that names the broken rule.
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
