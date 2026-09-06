from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Protocol, runtime_checkable

from flip7.cards import Card, CardKind, full_deck
from flip7.probability import DeckCounts, remaining_from_deck
from flip7.scoring import TARGET_SCORE
from flip7.state import PlayerLine


@dataclass(frozen=True)
class TableView:
    """Read-only table for policies: remaining **counts**, not draw order."""

    lines: tuple[PlayerLine, ...]
    remaining: DeckCounts
    totals: tuple[int, ...]
    dealer: int
    acting: int


class Policy(Protocol):
    name: str

    def decide(self, view: TableView) -> str:
        """Return ``hit`` or ``stay``."""
        ...


@runtime_checkable
class TargetingPolicy(Protocol):
    """Optional `Policy` extension (ADR-010): choose who a Freeze or Flip
    Three targets, among all currently active seats.

    This is a separate, ``runtime_checkable`` protocol rather than a
    required member of `Policy` on purpose: a method declared on a
    `Protocol` -- even with a concrete default body -- is only inherited by
    classes that explicitly subclass that `Protocol`; it is *not* picked up
    by classes that merely satisfy `Policy` structurally (confirmed against
    mypy directly). None of the five Phase 1 policies (`StayAfterDeal`,
    `ChaseFlip7`, `BustThreshold`, `OneStepEV`) subclass `Policy` -- they
    just happen to match its shape -- so making `choose_target` a required
    `Policy` member would force every one of them to grow a method they
    don't need just to keep passing strict type-checking. Instead, the
    engine detects support with ``isinstance(policy, TargetingPolicy)`` and
    falls back to a fixed default (`_default_active_target`) for any policy
    that doesn't implement it -- which today is all five built-in policies.
    """

    def choose_target(self, view: TableView, card: Card, candidates: tuple[int, ...]) -> int:
        """Return a seat from ``candidates`` to target with ``card``.

        ``candidates`` lists every currently **active** seat, including the
        acting seat itself -- self-targeting is a legal choice for both
        Freeze and Flip Three under official rules. Returning a seat
        outside ``candidates`` is treated the same as not implementing this
        method at all: the engine ignores it and falls back to
        `_default_active_target`.
        """
        ...


@dataclass
class RoundResult:
    scores: list[int]
    lines: list[PlayerLine]
    flip7_seat: int | None
    cards_dealt: int


@dataclass
class GameResult:
    winner: int | None
    totals: list[int]
    rounds: int
    round_scores: list[list[int]]
    busts: list[int]
    flip7s: list[int]


@dataclass
class _RoundState:
    """Mutable state threaded through one round's dealing and card resolution."""

    policies: list[Policy]
    lines: list[PlayerLine]
    pile: list[Card]
    totals: list[int]
    dealer: int
    n_players: int
    dealt: int = 0


def _visible_and_remaining(lines: list[PlayerLine], deck: list[Card]) -> DeckCounts:
    return remaining_from_deck(deck)


def _make_view(state: _RoundState, acting: int) -> TableView:
    return TableView(
        lines=tuple(state.lines),
        remaining=_visible_and_remaining(state.lines, state.pile),
        totals=tuple(state.totals),
        dealer=state.dealer,
        acting=acting,
    )


def _default_active_target(seat: int, lines: list[PlayerLine], n_players: int) -> int:
    """Fallback deterministic targeting rule (ADR-010).

    Next still-**active** seat after the drawer in turn order (dealer-order
    rotation), skipping busted/stayed/Flip-7'd lines; if no other seat is
    active, the drawer targets themself. Used for Freeze/Flip Three whenever
    the acting policy doesn't implement `TargetingPolicy`, and always for
    where a *redundant* second Second Chance goes (a fixed, simple rule --
    see ADR-010; that hand-off isn't routed through `TargetingPolicy` since
    only Freeze/Flip Three targeting was asked to be policy-driven).
    """
    for offset in range(1, n_players):
        candidate = (seat + offset) % n_players
        if lines[candidate].active:
            return candidate
    return seat


def _choose_action_target(seat: int, state: _RoundState, card: Card) -> int:
    """Target for a Freeze or Flip Three (ADR-010).

    Any currently active seat is a legal target, including the drawer
    themself, per official rules. The acting policy picks via the optional
    `TargetingPolicy.choose_target` extension; if it doesn't implement that
    (true of all five built-in Phase 1 policies today), the engine falls
    back to `_default_active_target`.
    """
    candidates = tuple(i for i in range(state.n_players) if state.lines[i].active)
    if not candidates:
        candidates = (seat,)
    policy = state.policies[seat]
    if isinstance(policy, TargetingPolicy):
        view = _make_view(state, seat)
        target = policy.choose_target(view, card, candidates)
        if target in candidates:
            return target
    return _default_active_target(seat, state.lines, state.n_players)


def _draw_and_resolve(seat: int, state: _RoundState) -> tuple[str, int | None]:
    """Draw one card for ``seat`` and resolve its effect.

    Returns ``(outcome, flip7_seat)``:

    - ``outcome`` is ``seat``'s own draw result (``ok``/``bust``/``flip7``);
      action cards that target someone else always report ``ok`` for the
      drawer, since drawing them doesn't affect the drawer's own line.
    - ``flip7_seat`` is set to whichever seat hit Flip 7 as a *direct or
      cascading* result of this draw (a plain number card busting/completing
      the drawer's own line, or a Flip Three forcing a target into Flip 7),
      so ``play_round`` can end the round immediately either way.
    """
    lines = state.lines
    pile = state.pile
    if not pile:
        return "ok", None
    card = pile.pop()
    state.dealt += 1

    if card.kind is CardKind.FREEZE:
        lines[seat].cards.append(card)
        target = _choose_action_target(seat, state, card)
        lines[target].stayed = True
        return "ok", None

    if card.kind is CardKind.FLIP_THREE:
        lines[seat].cards.append(card)
        target = _choose_action_target(seat, state, card)
        flip7_seat: int | None = None
        for _ in range(3):
            if not pile or not lines[target].active:
                break
            outcome, nested_flip7 = _draw_and_resolve(target, state)
            if nested_flip7 is not None:
                flip7_seat = nested_flip7
            if outcome in ("bust", "flip7"):
                break
        return "ok", flip7_seat

    if card.kind is CardKind.SECOND_CHANCE:
        # Holding a second Second Chance has no extra effect, so a player who
        # already holds one passes the new copy to another active player
        # (ADR-010); otherwise they just hold onto it themselves.
        if lines[seat].second_chances == 0:
            target = seat
        else:
            target = _default_active_target(seat, lines, state.n_players)
        lines[target].apply(card)
        return "ok", None

    outcome = lines[seat].apply(card)
    if outcome == "flip7":
        return outcome, seat
    return outcome, None


def play_round(
    policies: list[Policy],
    rng: Random,
    *,
    dealer: int = 0,
    deck: list[Card] | None = None,
    totals: list[int] | None = None,
) -> RoundResult:
    n_players = len(policies)
    if deck is None:
        pile = full_deck()
        rng.shuffle(pile)
    else:
        pile = list(deck)
    lines = [PlayerLine() for _ in range(n_players)]
    state = _RoundState(
        policies=policies,
        lines=lines,
        pile=pile,
        totals=totals if totals is not None else [0] * n_players,
        dealer=dealer,
        n_players=n_players,
    )

    for i in range(n_players):
        seat = (dealer + i) % n_players
        if not state.pile:
            break
        if not lines[seat].active:
            # An earlier seat's opening Freeze/Flip Three already resolved
            # against this seat before their own initial card was dealt.
            continue
        _outcome, flip7_seat_deal = _draw_and_resolve(seat, state)
        if flip7_seat_deal is not None:
            return RoundResult(
                scores=[p.current_score() for p in lines],
                lines=lines,
                flip7_seat=flip7_seat_deal,
                cards_dealt=state.dealt,
            )

    flip7_seat: int | None = None
    while any(line.active for line in lines):
        acted = False
        for i in range(n_players):
            seat = (dealer + i) % n_players
            line = lines[seat]
            if not line.active:
                continue
            acted = True
            view = _make_view(state, seat)
            decision = policies[seat].decide(view)
            if decision == "stay" or not state.pile:
                line.stayed = True
                continue
            outcome, flip7_seat_hit = _draw_and_resolve(seat, state)
            if flip7_seat_hit is not None:
                flip7_seat = flip7_seat_hit
                return RoundResult(
                    scores=[p.current_score() for p in lines],
                    lines=lines,
                    flip7_seat=flip7_seat,
                    cards_dealt=state.dealt,
                )
            if outcome == "bust":
                continue
        if not acted:
            break

    return RoundResult(
        scores=[p.current_score() for p in lines],
        lines=lines,
        flip7_seat=flip7_seat,
        cards_dealt=state.dealt,
    )


def play_game(
    policies: list[Policy],
    rng: Random,
    *,
    target: int = TARGET_SCORE,
    max_rounds: int = 400,
) -> GameResult:
    n_players = len(policies)
    totals = [0] * n_players
    busts = [0] * n_players
    flip7s = [0] * n_players
    round_scores: list[list[int]] = []
    dealer = 0

    for round_i in range(max_rounds):
        result = play_round(policies, rng, dealer=dealer, totals=totals)
        for i, score in enumerate(result.scores):
            totals[i] += score
            if result.lines[i].busted:
                busts[i] += 1
        if result.flip7_seat is not None:
            flip7s[result.flip7_seat] += 1
        round_scores.append(result.scores)

        above = [i for i, t in enumerate(totals) if t >= target]
        if above:
            best = max(totals[i] for i in above)
            leaders = [i for i in above if totals[i] == best]
            if len(leaders) == 1:
                return GameResult(
                    winner=leaders[0],
                    totals=totals,
                    rounds=round_i + 1,
                    round_scores=round_scores,
                    busts=busts,
                    flip7s=flip7s,
                )
        dealer = (dealer + 1) % n_players

    return GameResult(
        winner=None,
        totals=totals,
        rounds=max_rounds,
        round_scores=round_scores,
        busts=busts,
        flip7s=flip7s,
    )
