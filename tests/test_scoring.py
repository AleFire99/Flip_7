from __future__ import annotations

from flip7.cards import NUMBER_COUNTS, PHASE1_DECK_SIZE, full_deck, number_card, plus_card, x2_card
from flip7.scoring import FLIP7_BONUS, score_line
from flip7.state import PlayerLine


def test_deck_size_and_recipe() -> None:
    deck = full_deck()
    assert len(deck) == PHASE1_DECK_SIZE
    numbers = [c.number for c in deck if c.number is not None]
    for n, count in NUMBER_COUNTS.items():
        assert numbers.count(n) == count
    plus = [c.plus for c in deck if c.plus is not None]
    assert sorted(plus) == [2, 4, 6, 8, 10]
    assert sum(1 for c in deck if c.double) == 1


def test_score_order_x2_then_plus_then_bonus() -> None:
    assert score_line([10, 11, 12], plus=8, has_x2=True, flip7=False) == 74
    assert score_line([10, 11, 12], plus=8, has_x2=True, flip7=True) == 74 + FLIP7_BONUS


def test_modifier_only_line() -> None:
    line = PlayerLine()
    assert line.apply(plus_card(2)) == "ok"
    assert line.apply(plus_card(6)) == "ok"
    assert line.apply(x2_card()) == "ok"
    assert line.current_score() == 8


def test_zero_counts_toward_flip7() -> None:
    line = PlayerLine()
    for n in (0, 1, 2, 3, 4, 5, 6):
        assert line.apply(number_card(n)) in {"ok", "flip7"}
    assert line.flip7
    assert line.current_score() == sum(range(7)) + FLIP7_BONUS


def test_duplicate_number_busts() -> None:
    line = PlayerLine()
    assert line.apply(number_card(12)) == "ok"
    assert line.apply(number_card(12)) == "bust"
    assert line.current_score() == 0
