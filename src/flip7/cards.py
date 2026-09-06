from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

PLUS_VALUES: tuple[int, ...] = (2, 4, 6, 8, 10)
NUMBER_COUNTS: dict[int, int] = {0: 1, 1: 1, **{n: n for n in range(2, 13)}}
PHASE1_DECK_SIZE = 85


class CardKind(Enum):
    NUMBER = auto()
    MODIFIER = auto()


@dataclass(frozen=True, slots=True, order=True)
class Card:
    kind: CardKind
    number: int | None = None
    plus: int | None = None
    double: bool = False

    def label(self) -> str:
        if self.kind is CardKind.NUMBER:
            return str(self.number)
        if self.double:
            return "x2"
        return f"+{self.plus}"


def number_card(n: int) -> Card:
    return Card(kind=CardKind.NUMBER, number=n)


def plus_card(value: int) -> Card:
    return Card(kind=CardKind.MODIFIER, plus=value)


def x2_card() -> Card:
    return Card(kind=CardKind.MODIFIER, double=True)


def full_deck() -> list[Card]:
    cards: list[Card] = []
    for n, count in NUMBER_COUNTS.items():
        cards.extend(number_card(n) for _ in range(count))
    for value in PLUS_VALUES:
        cards.append(plus_card(value))
    cards.append(x2_card())
    if len(cards) != PHASE1_DECK_SIZE:
        msg = f"expected {PHASE1_DECK_SIZE} cards, got {len(cards)}"
        raise RuntimeError(msg)
    return cards
