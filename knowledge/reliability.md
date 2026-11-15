# Number Duel Reliability

## [reliability-accepting-a-round] How a duel round is accepted

Every duel round goes through a safe service. The game engine first builds
a candidate state for the new round. An independent inspector then checks
the step from the old state to the candidate. Only if the inspector
accepts the step is the candidate saved as the new duel state.

## [reliability-inspector-checks] What the inspector checks

The inspector checks that the duel was still running and had rounds left,
that the settings and both secret numbers did not change, that exactly one
round was added and earlier rounds stayed the same, that both guesses are
whole numbers inside the range, that both hints match the secret numbers,
that Vector's range matches its whole history, and that the status
(playing, win or draw) is correct.

## [reliability-independent-inspector] Why the inspector is independent

The inspector does not call the game functions that it checks. It works
out the hints, Vector's range and the result again with its own number
comparisons. So a bug in the game engine cannot hide behind the engine's
own functions.

## [reliability-rejected-round] What happens when a round is rejected

When a round is rejected, the game state does not change. No round is
added, the round counter stays the same, and the old duel state is kept.
A rejected guess, such as a number outside the range, shows a clear
message. A round stopped by the inspector shows only a general message,
not the inner reason, and you can simply try again.

## [reliability-midpoint-not-required] Exact middle not required

The inspector checks that each of Vector's guesses lies inside the range
that is still possible at that moment. It does not require the guess to be
exactly the middle of that range. Another strategy that stays inside the
range would also pass the inspector.

## [reliability-logs] Logs without secrets

The safe service writes a log line for every round. An accepted round is
logged as duel_round_accepted with the round number and the new status. A
rejected round is logged as duel_round_rejected with the round number and
the stage, engine or guardrail. The logs never contain secret numbers or
full game states.

## [reliability-solo-scope] The Solo game is not inspected

Only Number Duel rounds go through the inspector. The Solo game uses its
own simpler rules and does not pass through the duel inspector.
