from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Protocol

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


def _visible_and_remaining(lines: list[PlayerLine], deck: list[Card]) -> DeckCounts:
    return remaining_from_deck(deck)


def _make_view(
    lines: list[PlayerLine],
    deck: list[Card],
    totals: list[int],
    dealer: int,
    acting: int,
) -> TableView:
    return TableView(
        lines=tuple(lines),
        remaining=_visible_and_remaining(lines, deck),
        totals=tuple(totals),
        dealer=dealer,
        acting=acting,
    )


def _choose_target(seat: int, lines: list[PlayerLine], n_players: int) -> int:
    """Deterministic action-card target (ADR-010).

    Freeze and Flip Three are aimed at the next still-**active** seat in
    turn order after the drawing seat (dealer-order rotation), skipping
    busted/stayed/flip7'd lines. If no other seat is active, the drawer
    targets themself. This is a placeholder rule -- picking a target
    strategically is issue #3's job; this only guarantees a target always
    exists.
    """
    for offset in range(1, n_players):
        candidate = (seat + offset) % n_players
        if lines[candidate].active:
            return candidate
    return seat


def _draw_and_resolve(
    seat: int,
    lines: list[PlayerLine],
    pile: list[Card],
    n_players: int,
    dealt_box: list[int],
) -> tuple[str, int | None]:
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
    if not pile:
        return "ok", None
    card = pile.pop()
    dealt_box[0] += 1

    if card.kind is CardKind.FREEZE:
        lines[seat].cards.append(card)
        target = _choose_target(seat, lines, n_players)
        lines[target].stayed = True
        return "ok", None

    if card.kind is CardKind.FLIP_THREE:
        lines[seat].cards.append(card)
        target = _choose_target(seat, lines, n_players)
        flip7_seat: int | None = None
        for _ in range(3):
            if not pile or not lines[target].active:
                break
            outcome, nested_flip7 = _draw_and_resolve(target, lines, pile, n_players, dealt_box)
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
            target = _choose_target(seat, lines, n_players)
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
    scores_so_far = totals if totals is not None else [0] * n_players
    dealt_box = [0]

    for i in range(n_players):
        seat = (dealer + i) % n_players
        if not pile:
            break
        if not lines[seat].active:
            # An earlier seat's opening Freeze/Flip Three already resolved
            # against this seat before their own initial card was dealt.
            continue
        _outcome, flip7_seat_deal = _draw_and_resolve(seat, lines, pile, n_players, dealt_box)
        if flip7_seat_deal is not None:
            return RoundResult(
                scores=[p.current_score() for p in lines],
                lines=lines,
                flip7_seat=flip7_seat_deal,
                cards_dealt=dealt_box[0],
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
            view = _make_view(lines, pile, scores_so_far, dealer, seat)
            decision = policies[seat].decide(view)
            if decision == "stay" or not pile:
                line.stayed = True
                continue
            outcome, flip7_seat_hit = _draw_and_resolve(seat, lines, pile, n_players, dealt_box)
            if flip7_seat_hit is not None:
                flip7_seat = flip7_seat_hit
                return RoundResult(
                    scores=[p.current_score() for p in lines],
                    lines=lines,
                    flip7_seat=flip7_seat,
                    cards_dealt=dealt_box[0],
                )
            if outcome == "bust":
                continue
        if not acted:
            break

    return RoundResult(
        scores=[p.current_score() for p in lines],
        lines=lines,
        flip7_seat=flip7_seat,
        cards_dealt=dealt_box[0],
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
