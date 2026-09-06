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
        """Apply a drawn card. Returns ``ok``, ``bust``, or ``flip7``."""
        self.cards.append(card)
        if card.kind is CardKind.MODIFIER:
            if card.double:
                self.has_x2 = True
            elif card.plus is not None:
                self.plus += card.plus
            return "ok"
        n = card.number
        if n is None:
            msg = "number card missing value"
            raise ValueError(msg)
        if n in self.numbers:
            self.busted = True
            return "bust"
        self.numbers.append(n)
        if self.unique_count >= 7:
            return "flip7"
        return "ok"
