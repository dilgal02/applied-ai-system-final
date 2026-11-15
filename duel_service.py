import logging

from duel_logic import DuelState, play_round
from guardrails import validate_transition

logger = logging.getLogger(__name__)


class GuardrailViolation(ValueError):
    """The game engine produced a round that failed the guardrail check."""


def safe_play_round(state: DuelState, player_guess: int) -> DuelState:
    """Play one round and accept it only after the guardrail check passes.

    The engine (play_round) builds a candidate state, and the inspector
    (validate_transition) checks the step from state to the candidate.
    The candidate is returned only when the check passes. The given
    state is never changed.

    Raises:
        ValueError: the engine rejected the move (for example, a bad
            guess). The engine's error is raised again unchanged.
        GuardrailViolation: the engine returned a state that broke a
            game rule. Its message is general and has no secret numbers.
    """
    round_number = len(state.rounds) + 1

    try:
        candidate = play_round(state, player_guess)
    except ValueError:
        logger.warning(
            "duel_round_rejected round=%d stage=engine", round_number
        )
        raise

    try:
        validate_transition(state, candidate)
    except ValueError as error:
        logger.warning(
            "duel_round_rejected round=%d stage=guardrail", round_number
        )
        raise GuardrailViolation(
            "The game produced an invalid round, so it was not accepted."
        ) from error

    logger.info(
        "duel_round_accepted round=%d status=%s",
        round_number,
        candidate.status,
    )
    return candidate
