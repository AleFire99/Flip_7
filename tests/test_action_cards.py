from __future__ import annotations

import random

from flip7.cards import (
    ACTION_CARD_COPIES,
    PHASE1_DECK_SIZE,
    PHASE2_DECK_SIZE,
    CardKind,
    flip_three_card,
    freeze_card,
    full_deck,
    number_card,
    plus_card,
    second_chance_card,
)
from flip7.engine import play_round


class Scripted:
    name = "scripted"

    def __init__(self, moves: list[str]) -> None:
        self._moves = list(moves)

    def decide(self, view: object) -> str:
        if not self._moves:
            return "stay"
        return self._moves.pop(0)


def _pile(*cards: object) -> list:  # type: ignore[type-arg]
    """First argument is dealt first (engine pops from the end)."""
    return list(reversed(cards))


def test_deck_with_actions_is_94_cards_phase1_unchanged() -> None:
    phase1 = full_deck()
    assert len(phase1) == PHASE1_DECK_SIZE == 85

    phase2 = full_deck(include_action_cards=True)
    assert len(phase2) == PHASE2_DECK_SIZE == 94
    for kind in (CardKind.FREEZE, CardKind.FLIP_THREE, CardKind.SECOND_CHANCE):
        assert sum(1 for c in phase2 if c.kind is kind) == ACTION_CARD_COPIES == 3


def test_freeze_banks_target_mid_round_without_asking_them() -> None:
    deck = _pile(
        number_card(1),
        number_card(2),
        number_card(3),
        freeze_card(),
    )
    seat1_policy = Scripted(["hit"])
    result = play_round(
        [Scripted(["hit"]), seat1_policy, Scripted(["stay"])],
        random.Random(0),
        deck=deck,
    )
    # Seat 1 is frozen (banked) by seat 0's Freeze before ever being asked.
    assert result.lines[1].stayed is True
    assert seat1_policy._moves == ["hit"]  # never consulted
    assert result.scores == [1, 2, 3]


def test_flip_three_forced_draws_stop_on_mid_sequence_bust() -> None:
    deck = _pile(
        number_card(9),
        number_card(5),
        flip_three_card(),
        number_card(6),
        number_card(5),  # duplicate -> bust, 3rd forced draw must be skipped
    )
    result = play_round(
        [Scripted(["hit"]), Scripted(["hit"])],
        random.Random(0),
        deck=deck,
    )
    assert result.cards_dealt == 5
    assert result.lines[1].busted is True
    assert result.lines[1].numbers == [5, 6]
    assert result.scores == [9, 0]


def test_flip_three_forced_draws_stop_on_mid_sequence_flip7() -> None:
    deck = _pile(
        number_card(0),
        number_card(1),
        plus_card(2),
        number_card(2),
        plus_card(2),
        number_card(3),
        plus_card(2),
        number_card(4),
        plus_card(2),
        number_card(5),
        plus_card(2),
        number_card(6),
        flip_three_card(),
        plus_card(2),
        number_card(7),  # 7th unique -> Flip 7 on the 2nd forced draw
        number_card(9),  # sentinel: must NOT be drawn as a 3rd forced draw
    )
    result = play_round(
        [Scripted(["hit"] * 6), Scripted(["hit"] * 5)],
        random.Random(0),
        deck=deck,
    )
    assert result.flip7_seat == 1
    assert result.lines[1].unique_count == 7
    assert 9 not in result.lines[1].numbers
    assert result.cards_dealt == 15  # sentinel card left undrawn


def test_second_chance_cancels_one_bust_then_is_consumed() -> None:
    deck = _pile(
        number_card(5),
        second_chance_card(),
        number_card(5),  # duplicate -> protected by the Second Chance
        number_card(5),  # duplicate again -> busts for real, no protection left
    )
    result = play_round(
        [Scripted(["hit", "hit", "hit"])],
        random.Random(0),
        deck=deck,
    )
    assert result.lines[0].numbers == [5]
    assert result.lines[0].second_chances == 0
    assert result.lines[0].busted is True
    assert result.scores == [0]


def test_second_chance_is_passed_on_when_already_held() -> None:
    # Seat 1 must still be active (not yet stayed) when seat 0 draws its
    # *second* Second Chance, so there is another active player to receive it.
    deck = _pile(
        number_card(1),
        number_card(2),
        second_chance_card(),
        plus_card(3),
        second_chance_card(),
    )
    result = play_round(
        [Scripted(["hit", "hit"]), Scripted(["hit"])],
        random.Random(0),
        deck=deck,
    )
    assert result.lines[0].second_chances == 1
    assert result.lines[1].second_chances == 1
