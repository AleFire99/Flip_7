from __future__ import annotations

from dataclasses import dataclass, field

from flip7.cards import NUMBER_COUNTS, PLUS_VALUES, Card, CardKind


@dataclass
class DeckCounts:
    numbers: dict[int, int] = field(default_factory=dict)
    plus: dict[int, int] = field(default_factory=dict)
    x2: int = 0

    @property
    def total(self) -> int:
        return sum(self.numbers.values()) + sum(self.plus.values()) + self.x2


def full_counts() -> DeckCounts:
    return DeckCounts(
        numbers=dict(NUMBER_COUNTS),
        plus=dict.fromkeys(PLUS_VALUES, 1),
        x2=1,
    )


def counts_from_cards(cards: list[Card]) -> DeckCounts:
    counts = DeckCounts(
        numbers=dict.fromkeys(NUMBER_COUNTS, 0),
        plus=dict.fromkeys(PLUS_VALUES, 0),
        x2=0,
    )
    for card in cards:
        if card.kind is CardKind.NUMBER and card.number is not None:
            counts.numbers[card.number] = counts.numbers.get(card.number, 0) + 1
        elif card.double:
            counts.x2 += 1
        elif card.plus is not None:
            counts.plus[card.plus] = counts.plus.get(card.plus, 0) + 1
    return counts


def subtract_visible(visible: list[Card]) -> DeckCounts:
    remaining = full_counts()
    seen = counts_from_cards(visible)
    for n, c in seen.numbers.items():
        remaining.numbers[n] -= c
    for v, c in seen.plus.items():
        remaining.plus[v] -= c
    remaining.x2 -= seen.x2
    return remaining


def p_bust(held_numbers: list[int], remaining: DeckCounts) -> float:
    n = remaining.total
    if n <= 0:
        return 0.0
    bust_cards = sum(remaining.numbers.get(k, 0) for k in held_numbers)
    return bust_cards / n


def p_new_number(held_numbers: list[int], remaining: DeckCounts) -> float:
    n = remaining.total
    if n <= 0:
        return 0.0
    held = set(held_numbers)
    new = sum(c for k, c in remaining.numbers.items() if k not in held)
    return new / n


def p_modifier(remaining: DeckCounts) -> float:
    n = remaining.total
    if n <= 0:
        return 0.0
    return (sum(remaining.plus.values()) + remaining.x2) / n


def p_flip7_this_hit(held_numbers: list[int], remaining: DeckCounts) -> float:
    if len(held_numbers) != 6:
        return 0.0
    return p_new_number(held_numbers, remaining)


def one_step_ev(
    numbers: list[int],
    plus: int,
    has_x2: bool,
    remaining: DeckCounts,
    *,
    busted: bool = False,
) -> float:
    """Expected banked score after exactly one more card (then stay)."""
    from flip7.scoring import score_line

    if busted:
        return 0.0
    n = remaining.total
    if n <= 0:
        return score_line(numbers, plus, has_x2, len(numbers) >= 7)

    ev = 0.0
    held = set(numbers)
    for k, count in remaining.numbers.items():
        if count <= 0:
            continue
        p = count / n
        if k in held:
            continue
        new_numbers = [*numbers, k]
        ev += p * score_line(new_numbers, plus, has_x2, len(new_numbers) >= 7)
    for value, count in remaining.plus.items():
        if count <= 0:
            continue
        ev += (count / n) * score_line(numbers, plus + value, has_x2, False)
    if remaining.x2 > 0:
        ev += (remaining.x2 / n) * score_line(numbers, plus, True, False)
    return ev


def remaining_from_deck(deck: list[Card]) -> DeckCounts:
    return counts_from_cards(deck)
