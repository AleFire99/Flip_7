# Flip 7 rules (Phase 1)

Subset used by this codebase. Official action cards are omitted (see [DECISIONS.md](DECISIONS.md) ADR-001).
Freeze, Flip Three, and Second Chance are now implemented as a Phase 2 plugin — see [RULES_PHASE2.md](RULES_PHASE2.md).

## Goal

First player to **200** or more after a round wins. If two or more players are **tied** at the highest total and that total is at least 200, play another round until one leader remains.

## Deck (85 cards)

**Numbers (79):** one `0`, one `1`, then `n` copies of value `n` for `n = 2..12`.

**Modifiers (6):** one each of `+2`, `+4`, `+6`, `+8`, `+10`, `x2`.

## Round

1. Shuffle. Dealer deals one face-up card to each player, including the dealer.
2. In turn order starting at the dealer, each **active** player Hits or Stays.
3. Hit: receive exactly one card, then pass the turn.
4. Duplicate **number** (a value already in that player's line) → **bust**, score 0 for the round.
5. Modifiers never bust and never count toward Flip 7. You may bank a line that is only modifiers.
6. **Flip 7:** seven unique number cards (0 counts; modifiers do not). The round ends at once. That player scores the line **plus 15**. Other non-busted players score their current lines.
7. The round also ends when every player has stayed or busted.

You may stay only if you already have at least one card (always true after the initial deal).

## Scoring a non-busted line

1. Sum number card values.
2. If `x2` is present, double that sum (not modifiers, not the Flip 7 bonus).
3. Add all `+` modifiers.
4. If Flip 7, add 15.

Example: numbers `10+11+12=33`, `x2` → 66, `+8` → 74. Flip 7 would then add 15 → 89.
