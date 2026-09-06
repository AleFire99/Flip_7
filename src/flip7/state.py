from __future__ import annotations

from dataclasses import dataclass, field

from flip7.cards import Card, CardKind
from flip7.scoring import score_line


@dataclass
class PlayerLine:
    numbers: list[int] = field(default_factory=list)
    plus: int = 0
    has_x2: bool = False
    busted: bool = False
    stayed: bool = False
    cards: list[Card] = field(default_factory=list)
    #: Held, unused Second Chance cards (ADR-010). Normally 0 or 1, but a
    #: player can end up holding more if others keep passing extras to them.
    second_chances: int = 0

    @property
    def unique_count(self) -> int:
        return len(self.numbers)

    @property
    def flip7(self) -> bool:
        return not self.busted and self.unique_count >= 7

    @property
    def active(self) -> bool:
        return not self.busted and not self.stayed and not self.flip7

    def current_score(self) -> int:
        if self.busted:
            return 0
        return score_line(self.numbers, self.plus, self.has_x2, self.flip7)

    def apply(self, card: Card) -> str:
        """Apply a drawn card that affects *this* line directly.

        Returns ``ok``, ``bust``, or ``flip7``. Handles NUMBER, MODIFIER, and
        SECOND_CHANCE cards (a Second Chance is always held by whichever line
        this method is called on -- see ADR-010). Freeze and Flip Three are
        not resolved here: they change *another* line's state or require
        drawing extra cards from the shared pile, so ``flip7.engine`` handles
        them directly against ``TableView``/the pile instead of routing
        through a single line's ``apply``.
        """
        self.cards.append(card)
        if card.kind is CardKind.MODIFIER:
            if card.double:
                self.has_x2 = True
            elif card.plus is not None:
                self.plus += card.plus
            return "ok"
        if card.kind is CardKind.SECOND_CHANCE:
            self.second_chances += 1
            return "ok"
        if card.kind is not CardKind.NUMBER:
            msg = f"PlayerLine.apply cannot resolve {card.kind}; engine must handle targeting"
            raise ValueError(msg)
        n = card.number
        if n is None:
            msg = "number card missing value"
            raise ValueError(msg)
        if n in self.numbers:
            if self.second_chances > 0:
                # Second Chance cancels exactly one bust and is consumed (ADR-010).
                self.second_chances -= 1
                return "ok"
            self.busted = True
            return "bust"
        self.numbers.append(n)
        if self.unique_count >= 7:
            return "flip7"
        return "ok"
