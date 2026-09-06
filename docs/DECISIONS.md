# Decisions

Architecture Decision Records for this analysis workspace. Status is `accepted` unless noted.

## ADR-001: Phase 1 excludes action cards

**Context:** Official Flip 7 includes Freeze, Flip Three, and Second Chance (9 cards). Those change targeting, forced draws, and bust protection.

**Decision:** Phase 1 uses an 85-card deck: 79 number cards plus 6 modifiers (`+2`, `+4`, `+6`, `+8`, `+10`, `x2`). Action cards are out of scope until a later engine plugin.

**Consequences:** Bust rates and Flip 7 rates will not match the published 94-card game. Comparisons across phases must restate the deck.

## ADR-002: Perfect information (face-up table)

**Context:** Every card is dealt face up, so every player sees every line.

**Decision:** Policies receive remaining **counts**, not the shuffled order of undealt cards. The engine keeps a hidden order for drawing.

**Consequences:** Hit/stay math is exact given the visible table. A policy that inspected the remaining list would cheat; the `TableView` API does not expose order.

## ADR-003: Analysis option A first; B and C later

**Context:** Three analysis depths were considered:

- **A:** Exact one-step hit vs stay EV from remaining counts, then 3-player race-to-200 simulations.
- **B:** Recursive EV assuming other players stay out of the way, plus competing-policy tables.
- **C:** Full opponent modeling and endgame race (stop Flip 7 / catch 200).

**Decision:** Implement A now. Document B and C as follow-ups; do not build them in Phase 1.

**Consequences:** The default `OneStepEV` policy is **myopic**. It does not value extra future hits after a successful card, and it does not model an opponent Flip 7 locking the current totals.

## ADR-004: Tooling (uv, Git Flow, Conventional Commits)

**Context:** Need a reproducible research repo with reviewable slices.

**Decision:**

- Package and lockfile via **uv**, `src/` layout, Python 3.12+.
- **Git Flow:** `main`, `develop`, `feature/*`, PRs into `develop`.
- **Conventional Commits** (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
- GitHub issues (one per slice) and pull requests.

**Consequences:** Bootstrap lands on `main`/`develop` first; features merge through PRs.

## ADR-005: Scoring order

**Context:** Official FAQ: sum number cards, apply `x2` to that sum only, add plus modifiers, then +15 if Flip 7. Bust scores 0. Modifier-only lines score the plus cards; `x2` with no numbers is 0 plus any `+` cards.

**Decision:** `flip7.scoring.score_line` implements that order. Flip 7 bonus is not doubled.

**Consequences:** Matches published scoring for Phase 1 cards.

## ADR-006: Default study is 3 players, race to 200

**Context:** The game is 3+ players; first past 200 after a round wins. Official FAQ: if two or more players are tied with scores over 200, continue rounds until there is a single winner.

**Decision:** Simulator default is 3 seats, target 200. If several players are at or above 200, the unique highest total wins; a tie at that high score continues. Dealer rotates each round. Round cap exists only to bound runaway ties.

**Consequences:** Win rates include dealer rotation. Seat 0 is not a permanent first actor.

## ADR-007: Turn order and empty deck

**Context:** Rulebook: after the initial deal, the dealer offers hit or stay in turn. User description: a hit deals one card, then play passes.

**Decision:**

- Initial deal is one card per seat, starting at the dealer, wrapping around.
- Hit/stay also starts at the dealer each cycle. A hit draws **one** card, then the next seat acts.
- Flip 7 ends the round immediately; non-busted seats bank their current line.
- If the undealt pile is empty, a hit is treated as stay (all remaining cards are already in lines).

**Consequences:** This is not blackjack-style “keep hitting on your turn.” Empty-deck stays should be rare with 3 players and 85 cards.

## ADR-008: One-step EV definition

**Context:** Need a closed-form hit value from remaining counts.

**Decision:** Stay value is the current line score (0 if busted). Hit value is the expected score if exactly one more card is drawn and the player then banks (bust → 0; seven unique numbers → score with +15).

**Consequences:** Conservative when the true optimum is “hit again if the next card is safe.” That extension is option B.

## ADR-009: Later work (not built)

**Option B:** Dynamic programming over own line + remaining counts, assuming other seats stay (or already stayed). Then mixed-policy simulation tables.

**Option C:** Search or learned policies that freeze/endgame-race once action cards exist; until then, only implicit race via Flip 7 ending the round.

**Action cards:** Add Freeze, Flip Three, and Second Chance as engine plugins on the 94-card deck without rewriting scoring.

## ADR-010: Action-card engine plugin (Freeze, Flip Three, Second Chance) and targeting

**Context:** ADR-009 deferred Freeze, Flip Three, and Second Chance to a later engine plugin on the 94-card deck. Issue #3 (opponent-aware policies) is not yet started, so no policy exists that can strategically choose *who* a Freeze or Flip Three should target, or who a redundant Second Chance should go to. The plugin still needs a concrete, deterministic answer today so the rest of the engine (and its tests) can be exact and reproducible.

**Decision:**

- `flip7.cards.full_deck(include_action_cards: bool = False)` keeps the default 85-card Phase 1 deck; `include_action_cards=True` (or the `full_deck_with_actions()` alias) builds the 94-card deck with 3 copies each of the new `CardKind.FREEZE`, `CardKind.FLIP_THREE`, and `CardKind.SECOND_CHANCE`.
- Drawing an action card still counts as the drawer's one card for that hit (ADR-007); the effect resolves immediately as part of that draw, including when it is the initial face-up card or a card drawn mid-Flip-Three.
- **Targeting rule:** target the next still-**active** seat after the drawing seat, in turn order (dealer-order rotation), skipping busted/stayed/Flip-7'd lines; if no other seat is active, target yourself. This same rule decides Freeze's and Flip Three's target, and where a *second* held Second Chance goes when the drawer already holds one (if nobody else is active, the drawer just keeps the extra copy, since holding more than one has no additional effect). This is a placeholder, not a strategy: full opponent-aware target selection is issue #3's job once such policies exist. The mechanism (an explicit target seat, computed once per action card) already exists so issue #3 can later replace `flip7.engine._choose_target` with a policy-driven choice without changing anything else.
- **Freeze:** bank the target's line (`PlayerLine.stayed = True`) immediately, regardless of whose turn it is.
- **Flip Three:** force the target to draw 3 cards back-to-back with no stay option; a mid-sequence bust or Flip 7 applies its consequence immediately and skips any remaining forced draws in that sequence.
- **Second Chance:** held by whoever it resolves for (`PlayerLine.second_chances`, an int since a player can end up holding more than one via redistribution). A number-card bust is cancelled by consuming one held Second Chance instead (the duplicate card is discarded, no bust); this is a one-time use per copy held.
- `flip7.scoring.score_line` is untouched: action cards never enter a line's numbers/plus/x2 and never count toward the Flip 7 unique-card check.

**Consequences:** Freeze/Flip Three targeting is deterministic but not strategic (it never picks the "best" target for the drawer) until issue #3 lands. `flip7.probability`'s `DeckCounts`/EV math (issue #1's territory) still only tracks numbers/plus/x2, so it undercounts `remaining.total` whenever action cards remain in a 94-card pile; this only matters once code actually simulates on the 94-card deck; it is out of scope for this ADR.
