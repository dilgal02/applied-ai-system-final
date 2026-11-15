# Number Duel Rules

## [rules-overview] What Number Duel is

Number Duel is a two-player number guessing game. You play against Vector,
a computer opponent. Each side picks a secret number, and each side tries
to guess the other side's secret number first.

## [rules-difficulty-limits] Difficulty ranges and round limits

The difficulty sets the range of possible numbers and the round limit.
Easy uses the numbers 1 to 20 and allows 6 rounds. Normal uses the numbers
1 to 100 and allows 8 rounds. Hard uses the numbers 1 to 50 and allows only
5 rounds. Both secret numbers and every guess must be inside the range.

## [rules-starting-a-duel] Starting a duel

Before the duel you choose a difficulty and enter your secret number.
Vector's secret number is drawn at random only when you press Start Duel.
During the duel the difficulty and both secret numbers do not change.
Vector's secret number is shown only after the duel ends.

## [rules-paired-rounds] Paired rounds

Every round has two moves, and both players always get their move. First
you guess Vector's secret number, then Vector guesses your secret number.
Vector still makes its move in a round where you already guessed right.
One round uses one attempt from the round limit.

## [rules-hints] Hints after each guess

Every guess gets one hint. "Too Low" means the guess is smaller than the
secret number. "Too High" means the guess is bigger than the secret number.
"Win" means the guess is correct.

## [rules-win-and-draw] Winning and draws

The result is decided after both moves of a round. If both players guess
correctly in the same round, the duel is a draw. If only you guess
correctly, you win. If only Vector guesses correctly, Vector wins. If
nobody guesses correctly and the round limit is reached, the duel is a
draw. Otherwise the duel goes on to the next round.

## [rules-valid-guesses] Valid guesses

A guess must be a whole number inside the range of the difficulty. An
empty guess, text, a fraction such as 4.5, or a number outside the range
is rejected with a message. A rejected guess does not use up a round.

## [rules-new-duel] Starting over with New Duel

The New Duel button is available during a duel and after it ends. It
clears the current duel and its history and goes back to the setup. The
chosen difficulty is kept. New Duel does not change the Solo game.
