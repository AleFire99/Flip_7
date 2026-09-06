# Flip 7 rules (Phase 2: action cards)

Adds the official Freeze, Flip Three, and Second Chance action cards on top
of [Phase 1](RULES_PHASE1.md). See [DECISIONS.md](DECISIONS.md) ADR-001,
ADR-009, and ADR-010 for the history and the targeting decision below.

## Deck (94 cards)

Phase 1's 85 cards (79 numbers + 6 modifiers), plus **9 action cards**: 3
copies each of Freeze, Flip Three, and Second Chance.

`flip7.cards.full_deck(include_action_cards=True)` (or the
`full_deck_with_actions()` alias) builds the 94-card deck.
`full_deck()` with no arguments still builds the original 85-card Phase 1
deck unchanged, so all existing Phase 1 behavior and tests are untouched.

## Action cards

Drawing an action card still counts as a player's one card for that hit
(ADR-007: one hit = one card, then the turn passes) — the difference is
*what* the card does instead of adding to the drawer's own line.

### Freeze (3 copies)

Played on a target: that player's turn ends immediately and their current
line is banked/locked for the round, exactly as if they had chosen to stay
— even if it wasn't their turn and even if they would rather have kept
hitting. A frozen player is not asked to hit/stay again this round.

### Flip Three (3 copies)

The target player must immediately draw 3 cards in a row, with no choice to
stay in between. If a bust or a Flip 7 happens partway through those 3
forced draws, that consequence applies immediately (the target's line busts,
or — if it's a Flip 7 — the round ends at once) and any remaining forced
draws in that Flip Three are skipped, never dealt.

Cards drawn during a forced Flip Three sequence are resolved exactly like
any other draw — including another Freeze, Flip Three, or Second Chance
turning up mid-sequence, which resolves immediately in turn (e.g. a nested
Flip Three keeps forcing draws for its own target before the outer sequence
continues).

### Second Chance (3 copies)

Held by whoever it's drawn for (played on self). If that player would bust
by drawing a number already in their line, a held Second Chance is discarded
instead, the duplicate card is discarded too, and no bust occurs. This is
one-time use: the held Second Chance is consumed and does not protect
against a second bust.

If a player draws a *second* Second Chance while already holding one, see
the targeting rule below for where the extra copy goes.

## Targeting mechanism (ADR-010)

Per official rules, whoever draws a Freeze or Flip Three may target **any**
currently active player, including themselves — not just "the next
player". Full strategic targeting (a policy that picks the *best* target)
is still out of scope here — that's issue #3's job, once opponent-aware
policies exist — but the mechanism to specify an arbitrary target already
exists:

- When a Freeze or Flip Three is drawn, the engine computes `candidates`:
  every currently active seat, including the drawer.
- If the acting player's policy implements the optional
  `flip7.engine.TargetingPolicy` protocol (one method,
  `choose_target(view, card, candidates) -> int`), the engine calls it and
  uses whatever seat it returns (as long as that seat is in `candidates`).
- Otherwise — true of all five built-in Phase 1 policies today, since none
  of them implement `TargetingPolicy` — the engine falls back to a fixed
  default:

  > **Target the next still-active seat after the drawing seat, in turn
  > order (dealer-order rotation), skipping any player who has already
  > busted, stayed, or hit Flip 7. If no other seat is active, target
  > yourself.**

A redundant second Second Chance (drawn while already holding one) always
uses that same default rule directly, rather than going through
`TargetingPolicy` — only Freeze/Flip Three targeting was made policy-driven.
If there's no other active player to hand the extra copy to, the drawer
just keeps it — holding more than one has no additional effect beyond the
first available use.

## Everything else

Scoring (`flip7.scoring.score_line`), Flip 7 detection, and the race-to-200
game loop are unchanged from Phase 1 — action cards never add to a line's
numbers/plus/x2 and never count toward the 7-unique-numbers Flip 7 check.
