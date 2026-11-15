import logging
from dataclasses import asdict, replace

import pytest

import duel_service
from duel_logic import create_duel, play_round
from duel_service import GuardrailViolation, safe_play_round

SECRETS = ("63", "27")


def make_state():
    return create_duel(
        low=1,
        high=100,
        attempt_limit=8,
        player_secret=63,
        bot_secret=27,
    )


def service_logs(caplog):
    """Messages written by duel_service during the test."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "duel_service"
    ]


def test_valid_round_is_accepted_and_logged(caplog):
    caplog.set_level(logging.INFO, logger="duel_service")
    state = make_state()
    snapshot = asdict(state)

    new_state = safe_play_round(state, 40)

    assert new_state is not state
    assert len(new_state.rounds) == 1
    round_ = new_state.rounds[0]
    assert (round_.player_guess, round_.player_outcome) == (40, "Too High")
    assert (round_.bot_guess, round_.bot_outcome) == (50, "Too Low")
    assert (new_state.bot_low, new_state.bot_high) == (51, 100)
    assert new_state.status == "playing"
    assert asdict(state) == snapshot

    logs = service_logs(caplog)
    assert "duel_round_accepted round=1 status=playing" in logs
    assert not any("duel_round_rejected" in line for line in logs)
    assert not any(s in line for line in logs for s in SECRETS)


def test_engine_error_is_raised_unchanged(caplog):
    caplog.set_level(logging.INFO, logger="duel_service")
    state = make_state()
    snapshot = asdict(state)

    with pytest.raises(ValueError, match="player_guess must be an int") as info:
        safe_play_round(state, "abc")

    # The engine's own error, not wrapped by the service.
    assert type(info.value) is ValueError
    assert not isinstance(info.value, GuardrailViolation)
    assert asdict(state) == snapshot

    logs = service_logs(caplog)
    assert "duel_round_rejected round=1 stage=engine" in logs
    assert not any("duel_round_accepted" in line for line in logs)
    # The error text itself is not logged.
    assert not any("must be an int" in line for line in logs)


def test_bad_engine_result_is_blocked_by_guardrail(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="duel_service")
    state = make_state()
    good_candidate = play_round(state, 40)
    assert good_candidate.status == "playing"
    # A broken engine claims the player won although nobody guessed right.
    bad_candidate = replace(good_candidate, status="player_won")
    monkeypatch.setattr(
        duel_service, "play_round", lambda *args, **kwargs: bad_candidate
    )
    snapshot = asdict(state)

    with pytest.raises(GuardrailViolation) as info:
        safe_play_round(state, 40)

    assert asdict(state) == snapshot
    # The real inspector found the problem; its reason is kept as the cause.
    assert isinstance(info.value.__cause__, ValueError)
    assert "expected 'playing'" in str(info.value.__cause__)
    # The user-facing message is general and has no secret numbers.
    assert not any(s in str(info.value) for s in SECRETS)

    logs = service_logs(caplog)
    assert "duel_round_rejected round=1 stage=guardrail" in logs
    assert not any("duel_round_accepted" in line for line in logs)
    assert not any("expected" in line for line in logs)
