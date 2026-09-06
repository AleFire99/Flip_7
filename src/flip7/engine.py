from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Protocol

from flip7.cards import Card, full_deck
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
    dealt = 0

    for i in range(n_players):
        seat = (dealer + i) % n_players
        if not pile:
            break
        card = pile.pop()
        dealt += 1
        outcome = lines[seat].apply(card)
        if outcome == "flip7":
            return RoundResult(
                scores=[p.current_score() for p in lines],
                lines=lines,
                flip7_seat=seat,
                cards_dealt=dealt,
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
            card = pile.pop()
            dealt += 1
            outcome = line.apply(card)
            if outcome == "bust":
                continue
            if outcome == "flip7":
                flip7_seat = seat
                return RoundResult(
                    scores=[p.current_score() for p in lines],
                    lines=lines,
                    flip7_seat=flip7_seat,
                    cards_dealt=dealt,
                )
        if not acted:
            break

    return RoundResult(
        scores=[p.current_score() for p in lines],
        lines=lines,
        flip7_seat=flip7_seat,
        cards_dealt=dealt,
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
