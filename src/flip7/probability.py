from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

from flip7.cards import NUMBER_COUNTS, PLUS_VALUES, Card, CardKind


@dataclass
class DeckCounts:
    numbers: dict[int, int] = field(default_factory=dict)
    plus: dict[int, int] = field(default_factory=dict)
    x2: int = 0
    #: Action-card copies still in the pile (Phase 2, ADR-021). All zero for the
    #: Phase 1 deck, so every Phase 1 probability is unchanged.
    freeze: int = 0
    flip_three: int = 0
    second_chance: int = 0

    @property
    def actions(self) -> int:
        return self.freeze + self.flip_three + self.second_chance

    @property
    def total(self) -> int:
        return sum(self.numbers.values()) + sum(self.plus.values()) + self.x2 + self.actions


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
        elif card.kind is CardKind.FREEZE:
            counts.freeze += 1
        elif card.kind is CardKind.FLIP_THREE:
            counts.flip_three += 1
        elif card.kind is CardKind.SECOND_CHANCE:
            counts.second_chance += 1
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


_LookaheadKey = tuple[frozenset[int], int, bool, tuple[object, ...]]

DEFAULT_LOOKAHEAD_CACHE_SIZE = 100_000


class _LookaheadCache:
    """Bounded LRU of top-level `lookahead_ev` results (ADR-017)."""

    def __init__(self, maxsize: int = DEFAULT_LOOKAHEAD_CACHE_SIZE) -> None:
        self.maxsize = maxsize
        self.hits = 0
        self.misses = 0
        self._data: OrderedDict[_LookaheadKey, float] = OrderedDict()

    def get(self, key: _LookaheadKey) -> float | None:
        value = self._data.get(key)
        if value is None:
            self.misses += 1
            return None
        self._data.move_to_end(key)
        self.hits += 1
        return value

    def put(self, key: _LookaheadKey, value: float) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._data)


_LOOKAHEAD_CACHE = _LookaheadCache()


def clear_lookahead_cache() -> None:
    """Drop every cached `lookahead_ev` result and reset hit/miss counters."""
    _LOOKAHEAD_CACHE.clear()


def lookahead_cache_info() -> dict[str, int]:
    return {
        "hits": _LOOKAHEAD_CACHE.hits,
        "misses": _LOOKAHEAD_CACHE.misses,
        "size": len(_LOOKAHEAD_CACHE),
        "maxsize": _LOOKAHEAD_CACHE.maxsize,
    }


def _lookahead_key(
    numbers: list[int],
    plus: int,
    has_x2: bool,
    remaining: DeckCounts,
    second_chances: int = 0,
    others_active: bool = True,
) -> _LookaheadKey:
    """Immutable snapshot of the full state (zero counts dropped so equal decks match)."""
    return (
        frozenset(numbers),
        plus,
        has_x2,
        (
            tuple(sorted((k, c) for k, c in remaining.numbers.items() if c > 0)),
            tuple(sorted((v, c) for v, c in remaining.plus.items() if c > 0)),
            remaining.x2,
            remaining.freeze,
            remaining.flip_three,
            remaining.second_chance,
            second_chances,
            others_active,
        ),
    )


def lookahead_ev(
    numbers: list[int],
    plus: int,
    has_x2: bool,
    remaining: DeckCounts,
    *,
    busted: bool = False,
    second_chances: int = 0,
    others_active: bool = True,
) -> float:
    """Cached optimal solo hit/stay EV (module-level bounded LRU, ADR-017).

    Phase 1 states (no action cards left in ``remaining`` and no held Second
    Chance) use :func:`_lookahead_ev_uncached`. Anything else uses
    :func:`_lookahead_ev_actions` (ADR-021), which models Second Chance,
    Freeze and Flip Three; ``second_chances`` is how many the line holds and
    ``others_active`` says whether another seat is still in the round (it
    decides where a drawn Freeze/Flip Three lands, as in the engine).
    """
    if busted:
        return 0.0
    key = _lookahead_key(numbers, plus, has_x2, remaining, second_chances, others_active)
    cached = _LOOKAHEAD_CACHE.get(key)
    if cached is not None:
        return cached
    if remaining.actions == 0 and second_chances == 0:
        value = _lookahead_ev_uncached(numbers, plus, has_x2, remaining)
    else:
        value = _lookahead_ev_actions(
            numbers, plus, has_x2, remaining, second_chances, others_active
        )
    _LOOKAHEAD_CACHE.put(key, value)
    return value


def _lookahead_ev_uncached(
    numbers: list[int],
    plus: int,
    has_x2: bool,
    remaining: DeckCounts,
    *,
    busted: bool = False,
) -> float:
    """Optimal solo hit/stay EV via recursive DP over own line + remaining counts.

    Unlike :func:`one_step_ev` (a single-card lookahead that always banks after
    the next draw), this recurses: at every hypothetical future state it picks
    ``max(stay_value, hit_value)`` again, so a "hit again if the next card was
    safe" chain is valued correctly. This is analysis option B (ADR-003/ADR-009):
    it assumes no other seat draws further cards from this point on -- it is the
    optimal policy for *this* line against the remaining deck, not a model of
    opponents.

    The state space is kept tractable by tracking only the *delta* from the
    starting line: which currently-unheld numbers get drawn, which of the (at
    most 5) plus cards get drawn, and whether the (at most 1) x2 card gets
    drawn. Because a repeat draw of an already-held number busts immediately
    (a terminal, non-recursive branch), a surviving path never draws the same
    number twice -- so this delta, plus the fixed starting ``remaining``,
    determines the remaining counts at every node without copying dicts. The
    delta is memoized as ``(new_numbers: frozenset[int], consumed_plus:
    frozenset[int], consumed_x2: bool)``, bounded by at most ``13 choose <=6``
    number subsets times ``32`` plus-card subsets times 2.
    """
    from flip7.scoring import score_line

    if busted:
        return 0.0
    original_numbers = frozenset(numbers)
    if len(original_numbers) >= 7:
        # Already Flip 7 (round would already have ended); bank with the bonus.
        return float(score_line(list(original_numbers), plus, has_x2, True))

    memo: dict[tuple[frozenset[int], frozenset[int], bool], float] = {}

    def solve(
        new_numbers: frozenset[int],
        consumed_plus: frozenset[int],
        consumed_x2: bool,
    ) -> float:
        key = (new_numbers, consumed_plus, consumed_x2)
        cached = memo.get(key)
        if cached is not None:
            return cached

        current_numbers = original_numbers | new_numbers
        current_plus = plus + sum(consumed_plus)
        current_has_x2 = has_x2 or consumed_x2
        stay_value = float(score_line(list(current_numbers), current_plus, current_has_x2, False))

        n_total = 0
        for k, base in remaining.numbers.items():
            n_total += base - (1 if k in new_numbers else 0)
        for v, base in remaining.plus.items():
            n_total += base - (1 if v in consumed_plus else 0)
        n_total += remaining.x2 - (1 if consumed_x2 else 0)

        if n_total <= 0:
            memo[key] = stay_value
            return stay_value

        hit_value = 0.0
        for k, base in remaining.numbers.items():
            count = base - (1 if k in new_numbers else 0)
            if count <= 0:
                continue
            p = count / n_total
            if k in current_numbers:
                continue  # duplicate draw busts the line: contributes 0
            grown = current_numbers | {k}
            if len(grown) >= 7:
                contrib = float(score_line(list(grown), current_plus, current_has_x2, True))
            else:
                contrib = solve(new_numbers | {k}, consumed_plus, consumed_x2)
            hit_value += p * contrib
        for v, base in remaining.plus.items():
            count = base - (1 if v in consumed_plus else 0)
            if count <= 0:
                continue
            p = count / n_total
            hit_value += p * solve(new_numbers, consumed_plus | {v}, consumed_x2)
        x2_count = remaining.x2 - (1 if consumed_x2 else 0)
        if x2_count > 0:
            p = x2_count / n_total
            hit_value += p * solve(new_numbers, consumed_plus, True)

        value = max(stay_value, hit_value)
        memo[key] = value
        return value

    return solve(frozenset(), frozenset(), False)


_N_NUM = 13
_PLUS_IDX = _N_NUM
_X2_IDX = _PLUS_IDX + len(PLUS_VALUES)
_FREEZE_IDX = _X2_IDX + 1
_FLIP3_IDX = _FREEZE_IDX + 1
_SC_IDX = _FLIP3_IDX + 1


def _neutral_indices(sc: int, others_active: bool) -> frozenset[int]:
    if not others_active:
        return frozenset()
    return frozenset({_FREEZE_IDX, _FLIP3_IDX, *([_SC_IDX] if sc > 0 else [])})


def _lookahead_ev_actions(
    numbers: list[int],
    plus: int,
    has_x2: bool,
    remaining: DeckCounts,
    second_chances: int = 0,
    others_active: bool = True,
) -> float:
    """Optimal solo hit/stay EV including action cards (ADR-021).

    State is ``(held numbers, plus total, x2, Second Chances held, remaining
    counts)``. Rules mirror ``flip7.engine``/``docs/RULES_PHASE2.md``:

    - A duplicate number with a Second Chance held: both the Second Chance and
      the duplicate are discarded, no bust. (Approximation: the discarded
      duplicate is not removed from the remaining counts; the effect on later
      probabilities is one card out of dozens, and tracking it multiplies the
      state space ~10x.)
    - A Second Chance drawn while holding none is kept; one drawn while
      already holding one is passed on (no effect on this line).
    - Freeze / Flip Three drawn: with ``others_active`` the engine's default
      target is another seat, so this line is unaffected; the DP treats the
      draw as a redraw (an approximation: it ignores that the next decision
      point could differ, and the card leaving the deck). With no
      other active seat it targets this line: Freeze banks it at once; Flip
      Three forces three more draws (bust/Flip 7/Freeze handled inside).
    - Flip 7 ends the round; an empty pile forces a stay.
    """
    from flip7.scoring import score_line

    rem0 = (
        *(remaining.numbers.get(k, 0) for k in range(_N_NUM)),
        *(remaining.plus.get(v, 0) for v in PLUS_VALUES),
        remaining.x2,
        remaining.freeze,
        remaining.flip_three,
        remaining.second_chance,
    )
    memo: dict[tuple[object, ...], float] = {}

    def stay_value(held: frozenset[int], plus_t: int, x2: bool) -> float:
        return float(score_line(sorted(held), plus_t, x2, False))

    def decide(held: frozenset[int], plus_t: int, x2: bool, sc: int, rem: tuple[int, ...]) -> float:
        key: tuple[object, ...] = ("d", held, plus_t, x2, sc, rem)
        cached = memo.get(key)
        if cached is not None:
            return cached
        stay = stay_value(held, plus_t, x2)
        value = stay if sum(rem) <= 0 else max(stay, draw(held, plus_t, x2, sc, rem, 0))
        memo[key] = value
        return value

    def cont(
        held: frozenset[int],
        plus_t: int,
        x2: bool,
        sc: int,
        rem: tuple[int, ...],
        pending: int,
    ) -> float:
        if pending > 0:
            return draw(held, plus_t, x2, sc, rem, pending - 1)
        return decide(held, plus_t, x2, sc, rem)

    def draw(
        held: frozenset[int],
        plus_t: int,
        x2: bool,
        sc: int,
        rem: tuple[int, ...],
        pending: int,
    ) -> float:
        """Expected value of one draw followed by ``pending`` more forced draws."""
        # With another seat active, Freeze/Flip Three (and a Second Chance we
        # would have to pass on) just land elsewhere: treated as "redraw" --
        # skipped, with the draw probability renormalized over the cards that do
        # affect this line -- so they do not multiply the state space.
        skip = _neutral_indices(sc, others_active)
        total = sum(c for i, c in enumerate(rem) if i not in skip)
        if total <= 0:
            return stay_value(held, plus_t, x2)
        key: tuple[object, ...] = ("w", held, plus_t, x2, sc, rem, pending)
        cached = memo.get(key)
        if cached is not None:
            return cached
        value = 0.0
        for idx, count in enumerate(rem):
            if count <= 0 or idx in skip:
                continue
            p = count / total
            nxt = (*rem[:idx], count - 1, *rem[idx + 1 :])
            if idx < _N_NUM:
                if idx in held:
                    if sc > 0:
                        value += p * cont(held, plus_t, x2, sc - 1, rem, pending)
                    # else bust: contributes 0
                    continue
                grown = held | {idx}
                if len(grown) >= 7:
                    value += p * float(score_line(sorted(grown), plus_t, x2, True))
                else:
                    value += p * cont(grown, plus_t, x2, sc, nxt, pending)
            elif idx < _X2_IDX:
                plus_card = PLUS_VALUES[idx - _PLUS_IDX]
                value += p * cont(held, plus_t + plus_card, x2, sc, nxt, pending)
            elif idx == _X2_IDX:
                value += p * cont(held, plus_t, True, sc, nxt, pending)
            elif idx == _FREEZE_IDX:
                if others_active:
                    value += p * cont(held, plus_t, x2, sc, nxt, pending)
                else:
                    value += p * stay_value(held, plus_t, x2)
            elif idx == _FLIP3_IDX:
                extra = 0 if others_active else 3
                value += p * cont(held, plus_t, x2, sc, nxt, pending + extra)
            else:  # Second Chance: kept if none held, else passed on (or kept if alone)
                new_sc = sc + 1 if (sc == 0 or not others_active) else sc
                value += p * cont(held, plus_t, x2, new_sc, nxt, pending)
        memo[key] = value
        return value

    held0 = frozenset(numbers)
    if len(held0) >= 7:
        return float(score_line(sorted(held0), plus, has_x2, True))
    return decide(held0, plus, has_x2, second_chances, rem0)


def remaining_from_deck(deck: list[Card]) -> DeckCounts:
    return counts_from_cards(deck)
