# Number Duel Strategy

## [strategy-vector-binary-search] How Vector chooses its guess

Vector plays binary search. It keeps a range of numbers that are still
possible and always guesses the middle of that range, rounded down:
(low + high) // 2. Vector is a fixed algorithm, not a language model, so
the same situation always leads to the same guess.

## [strategy-vector-bounds] How Vector narrows its range

After each hint Vector updates its range. After "Too Low" the lowest
possible number becomes the guess plus one. After "Too High" the highest
possible number becomes the guess minus one. After "Win" the range shrinks
to the guessed number only. The range never contains a number that a hint
has already ruled out.

## [strategy-vector-inputs] What Vector's strategy sees

Vector's strategy only sees the bounds of its range. The function that
picks Vector's guess, choose_guess, receives only the low and high bounds.
The function that narrows the range, update_bounds, receives the bounds,
the guess and the hint. Neither function ever receives your secret number.
The game engine compares Vector's guess with your secret number to produce
the hint, like a referee.

## [strategy-first-guesses] Vector's first guess on each difficulty

Because Vector starts with the full range, its first guess is always the
same: 10 on Easy (range 1 to 20), 50 on Normal (range 1 to 100) and 25 on
Hard (range 1 to 50).

## [strategy-guesses-needed] How many guesses Vector needs

On Easy, Vector needs at most 5 guesses, and the limit is 6 rounds, so it
always finds your number in time. On Normal, Vector needs at most 7
guesses, and the limit is 8 rounds, so it also always finds your number in
time. On Hard, the range 1 to 50 sometimes needs 6 guesses, but the limit
is only 5 rounds. So on Hard the limit of 5 rounds is not always enough
for Vector.

## [strategy-hard-limit] Numbers Vector cannot reach on Hard

On Hard, Vector needs 6 guesses for 19 of the 50 possible numbers, so it
cannot find them within the 5-round limit: 2, 5, 8, 11, 14, 17, 20, 22,
24, 27, 30, 33, 35, 37, 40, 43, 46, 48 and 50. If your secret number is
one of them, Vector cannot win on Hard. You can still win by guessing
Vector's number, otherwise the duel ends in a draw at the limit.

## [strategy-your-guesses] Guessing Vector's number yourself

The fastest safe way to find Vector's number is the same method: guess the
middle of the numbers that are still possible and use each hint to cut the
range in half. With this method you also need at most 5 guesses on Easy,
7 on Normal and 6 on Hard. On Easy and Normal Vector always finds your
number within the limit, so to win you must guess its number in an
earlier round than it guesses yours. Guessing in the same round gives a
draw.
