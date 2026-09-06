from __future__ import annotations

from flip7.cards import CardKind, full_deck, number_card
from flip7.probability import (
    counts_from_cards,
    full_counts,
    one_step_ev,
    p_bust,
    p_flip7_this_hit,
    p_modifier,
    p_new_number,
    subtract_visible,
)
from flip7.scoring import score_line
from flip7.state import PlayerLine


def test_probabilities_partition_remaining() -> None:
    remaining = full_counts()
    held = [12, 11]
    parts = (
        p_bust(held, remaining),
        p_new_number(held, remaining),
        p_modifier(remaining),
    )
    assert abs(sum(parts) - 1.0) < 1e-12


def test_p_bust_matches_copy_counts() -> None:
    remaining = full_counts()
    assert p_bust([12], remaining) == 12 / remaining.total
    remaining.numbers[12] = 0
    assert p_bust([12], remaining) == 0.0


def test_one_step_ev_matches_enumeration() -> None:
    line = PlayerLine()
    line.apply(number_card(10))
    line.apply(number_card(5))
    visible = list(line.cards)
    remaining = subtract_visible(visible)
    held_keys = {(c.kind, c.number, c.plus, c.double) for c in visible}
    consumed = {k: 1 for k in held_keys}
    n = remaining.total
    expected = 0.0
    held = set(line.numbers)
    for card in full_deck():
        key = (card.kind, card.number, card.plus, card.double)
        if consumed.get(key, 0) > 0:
            consumed[key] -= 1
            continue
        if card.kind is CardKind.NUMBER and card.number in held:
            contrib = 0.0
        elif card.kind is CardKind.NUMBER:
            nums = [*line.numbers, card.number]
            contrib = score_line(nums, line.plus, line.has_x2, len(nums) >= 7)
        elif card.double:
            contrib = score_line(line.numbers, line.plus, True, False)
        else:
            contrib = score_line(line.numbers, line.plus + int(card.plus or 0), line.has_x2, False)
        expected += contrib / n
    got = one_step_ev(line.numbers, line.plus, line.has_x2, remaining)
    assert abs(got - expected) < 1e-9


def test_flip7_only_with_six_uniques() -> None:
    remaining = full_counts()
    assert p_flip7_this_hit([1, 2, 3], remaining) == 0.0
    six = [0, 1, 2, 3, 4, 5]
    assert p_flip7_this_hit(six, remaining) == p_new_number(six, remaining)


def test_counts_from_cards_roundtrip() -> None:
    deck = full_deck()
    assert counts_from_cards(deck).total == full_counts().total
