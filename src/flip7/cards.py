from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

PLUS_VALUES: tuple[int, ...] = (2, 4, 6, 8, 10)
NUMBER_COUNTS: dict[int, int] = {0: 1, 1: 1, **{n: n for n in range(2, 13)}}
PHASE1_DECK_SIZE = 85

#: Freeze, Flip Three, and Second Chance: 3 copies each (ADR-001/ADR-010).
ACTION_CARD_COPIES = 3
PHASE2_DECK_SIZE = PHASE1_DECK_SIZE + 3 * ACTION_CARD_COPIES


class CardKind(Enum):
    NUMBER = auto()
    MODIFIER = auto()
    FREEZE = auto()
    FLIP_THREE = auto()
    SECOND_CHANCE = auto()


@dataclass(frozen=True, slots=True, order=True)
class Card:
    kind: CardKind
    number: int | None = None
    plus: int | None = None
    double: bool = False

    def label(self) -> str:
        if self.kind is CardKind.NUMBER:
            return str(self.number)
        if self.kind is CardKind.MODIFIER:
            if self.double:
                return "x2"
            return f"+{self.plus}"
        if self.kind is CardKind.FREEZE:
            return "Freeze"
        if self.kind is CardKind.FLIP_THREE:
            return "Flip Three"
        return "Second Chance"


def number_card(n: int) -> Card:
    return Card(kind=CardKind.NUMBER, number=n)


def plus_card(value: int) -> Card:
    return Card(kind=CardKind.MODIFIER, plus=value)


def x2_card() -> Card:
    return Card(kind=CardKind.MODIFIER, double=True)


def freeze_card() -> Card:
    return Card(kind=CardKind.FREEZE)


def flip_three_card() -> Card:
    return Card(kind=CardKind.FLIP_THREE)


def second_chance_card() -> Card:
    return Card(kind=CardKind.SECOND_CHANCE)


def full_deck(*, include_action_cards: bool = False) -> list[Card]:
    """Build the Phase 1 deck (85 cards), or the Phase 2 deck (94) with actions.

    ``include_action_cards=False`` (default) preserves the original Phase 1
    85-card deck used throughout the codebase and its tests (ADR-001).
    ``include_action_cards=True`` adds 3 copies each of Freeze, Flip Three,
    and Second Chance for the 94-card Phase 2 deck (ADR-009/ADR-010).
    """
    cards: list[Card] = []
    for n, count in NUMBER_COUNTS.items():
        cards.extend(number_card(n) for _ in range(count))
    for value in PLUS_VALUES:
        cards.append(plus_card(value))
    cards.append(x2_card())
    if len(cards) != PHASE1_DECK_SIZE:
        msg = f"expected {PHASE1_DECK_SIZE} cards, got {len(cards)}"
        raise RuntimeError(msg)
    if not include_action_cards:
        return cards
    for _ in range(ACTION_CARD_COPIES):
        cards.append(freeze_card())
    for _ in range(ACTION_CARD_COPIES):
        cards.append(flip_three_card())
    for _ in range(ACTION_CARD_COPIES):
        cards.append(second_chance_card())
    if len(cards) != PHASE2_DECK_SIZE:
        msg = f"expected {PHASE2_DECK_SIZE} cards, got {len(cards)}"
        raise RuntimeError(msg)
    return cards


def full_deck_with_actions() -> list[Card]:
    """Convenience wrapper: the 94-card Phase 2 deck."""
    return full_deck(include_action_cards=True)
