from __future__ import annotations

import random

from flip7.cards import number_card
from flip7.engine import play_game, play_round
from flip7.scoring import FLIP7_BONUS, TARGET_SCORE
from flip7.strategy import BasicStrategy, ChaseFlip7, StayAfterDeal


class Scripted:
    name = "scripted"

    def __init__(self, moves: list[str]) -> None:
        self._moves = list(moves)

    def decide(self, view) -> str:
        if not self._moves:
            return "stay"
        return self._moves.pop(0)


def _pile(*cards):
    """First argument is dealt first (engine pops from the end)."""
    return list(reversed(cards))


def test_bust_on_duplicate_hit() -> None:
    deck = _pile(
        number_card(12),
        number_card(11),
        number_card(10),
        number_card(12),
    )
    result = play_round(
        [Scripted(["hit"]), StayAfterDeal(), StayAfterDeal()],
        random.Random(0),
        deck=deck,
    )
    assert result.lines[0].busted
    assert result.scores == [0, 11, 10]


def test_flip7_ends_round_and_others_bank() -> None:
    opening = [number_card(0), number_card(1), number_card(2)]
    hits = [number_card(n) for n in (3, 4, 5, 6, 7, 8)]
    deck = _pile(*opening, *hits)
    result = play_round(
        [ChaseFlip7(), StayAfterDeal(), StayAfterDeal()],
        random.Random(0),
        deck=deck,
    )
    assert result.flip7_seat == 0
    assert result.lines[0].unique_count == 7
    assert result.scores[0] == sum((0, 3, 4, 5, 6, 7, 8)) + FLIP7_BONUS
    assert result.scores[1] == 1
    assert result.scores[2] == 2


def test_game_unique_leader_over_target_wins() -> None:
    result = play_game(
        [StayAfterDeal(), StayAfterDeal(), StayAfterDeal()],
        random.Random(1),
        target=1,
        max_rounds=5,
    )
    assert result.winner is not None
    assert result.totals[result.winner] >= 1
    assert sum(1 for t in result.totals if t == max(result.totals)) >= 1


def test_target_constant() -> None:
    assert TARGET_SCORE == 200


def test_basic_strategy_hits_below_three_cards_then_stays_in_a_real_round() -> None:
    # The shipped chart (docs/DECISIONS.md ADR-013) hits with 0-2 unique
    # cards and stays at 3+, regardless of modifiers -- drive a real round
    # through the engine (mirroring the Scripted-policy pattern above) and
    # check it actually plays that way, not just that .decide() says so in
    # isolation.
    deck = _pile(
        number_card(5),  # initial deal: 1 unique card -> chart says hit
        number_card(6),  # 1st hit: 2 unique cards -> chart still says hit
        number_card(7),  # 2nd hit: 3 unique cards -> chart says stay next
        number_card(8),  # would only be drawn if the policy kept hitting
    )
    result = play_round([BasicStrategy()], random.Random(0), deck=deck)
    assert result.lines[0].numbers == [5, 6, 7]
    assert result.lines[0].stayed
    assert result.scores == [18]
