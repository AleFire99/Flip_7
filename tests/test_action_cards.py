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
from flip7.engine import TargetingPolicy, play_round
from flip7.strategy import ChaseFlip7, StayAfterDeal


class Scripted:
    name = "scripted"

    def __init__(self, moves: list[str]) -> None:
        self._moves = list(moves)

    def decide(self, view: object) -> str:
        if not self._moves:
            return "stay"
        return self._moves.pop(0)


class ScriptedTargeting(Scripted):
    """A Scripted policy that also implements `TargetingPolicy`, always
    picking a fixed, caller-chosen seat (used to prove arbitrary targeting,
    not just "next in line", is possible).
    """

    def __init__(self, moves: list[str], target: int) -> None:
        super().__init__(moves)
        self.target = target

    def choose_target(self, view: object, card: object, candidates: tuple[int, ...]) -> int:
        return self.target


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


def test_freeze_can_target_any_active_seat_not_just_the_next_one() -> None:
    # 4 players. The *default* targeting rule would pick seat 1 (next active
    # seat after the drawer, seat 0). A policy implementing `choose_target`
    # instead picks seat 3 -- a non-adjacent seat -- proving the mechanism
    # supports arbitrary choice among all active players, not just the
    # deterministic fallback's "next in line" rule.
    deck = _pile(
        number_card(1),
        number_card(2),
        number_card(3),
        number_card(4),
        freeze_card(),
        plus_card(2),
        plus_card(4),
    )
    seat1_policy = Scripted(["hit", "hit"])
    seat3_policy = Scripted(["hit"])
    result = play_round(
        [
            ScriptedTargeting(["hit"], target=3),
            seat1_policy,
            Scripted(["stay"]),
            seat3_policy,
        ],
        random.Random(0),
        deck=deck,
    )
    # Seat 3 (the chosen target) is frozen without ever being consulted.
    assert result.lines[3].stayed is True
    assert seat3_policy._moves == ["hit"]
    # Seat 1 (the *default* rule's target) was never frozen: it got to act
    # both of its scripted hits normally.
    assert seat1_policy._moves == []
    assert result.lines[1].stayed is True  # stayed on its own, after both hits
    assert result.scores == [1, 2 + 2 + 4, 3, 4]


def test_default_targeting_used_by_policies_without_choose_target() -> None:
    # Phase 1 policies (ChaseFlip7, StayAfterDeal, ...) never implement
    # choose_target. Confirm they still get a legal target via the engine's
    # default fallback rule (next active seat in turn order, else self).
    policy0 = ChaseFlip7()
    assert not isinstance(policy0, TargetingPolicy)
    deck = _pile(
        number_card(1),
        number_card(2),
        number_card(3),
        freeze_card(),
    )
    result = play_round(
        [policy0, StayAfterDeal(), StayAfterDeal()],
        random.Random(0),
        deck=deck,
    )
    assert result.lines[1].stayed is True  # default: next active seat after seat 0
