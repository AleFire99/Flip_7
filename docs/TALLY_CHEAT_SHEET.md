# Flip 7 tally cheat sheet (no probabilities needed)

1. Add up the values of the **number cards** you hold (ignore `+` and `x2` cards in the sum).
2. Count how many **different numbers** you hold.
3. Find your row. **Stay once your sum reaches the number; otherwise hit.**

| Different numbers held | No x2: `+` 0 | `+` 1-5 | `+` 6+ | x2 held: `+` 0 | `+` 1-5 | `+` 6+ |
|---|---|---|---|---|---|---|
| 0 or 1 | always hit | | | always hit | | |
| 2 | 23 | 21 | 20 | 22 | 22 | 21 |
| 3 | 24 | 23 | 21 | 23 | 23 | 22 |
| 4 | 25 | 24 | 22 | 24 | 23 | 23 |
| 5 | 27 | 26 | 24 | 25 | 24 | 24 |
| 6 (one card from Flip 7) | 36 | 35 | 33 | 31 | 30 | 30 |

`+` is the total of the `+2/+4/+6/+8/+10` cards you hold. At 7 different numbers the
round is already over (Flip 7).

## Why these numbers

- Each number `n` (for 2-12) has `n` copies in the deck, so the sum of what you hold tracks how
  likely the next card is a duplicate; staying becomes right at roughly 27% bust risk (about 40%
  when one card from Flip 7, because the +15 bonus is worth chasing).
- `x2` and `+` cards raise what you bank by staying, so you stop a little earlier: by 1-3 points,
  or about 5 with `x2` one card from Flip 7.
- Thresholds are fitted to the exact lookahead solver over every possible hand of 0-6 numbers
  (97-100% agreement per row). Measured over 2,500 seat-swapped game pairs the tally wins as often
  as the exact-probability chart (50.2% [49.3, 51.1]) -- see ADR-019 and ADR-022.
- With a **Second Chance** in front of you, always hit (it cancels your first duplicate).

Source of truth: `flip7.basic_strategy.TALLY_STAY_THRESHOLDS`.
