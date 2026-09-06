from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import combinations, product
from random import Random

from flip7.cards import NUMBER_COUNTS, PLUS_VALUES
from flip7.probability import DeckCounts, full_counts, lookahead_ev, p_bust
from flip7.scoring import score_line

#: A chartable state: (a coarse label for this line's exact P(bust) against
#: the remaining deck; whether this hand is one card from Flip 7 -- the +15
#: bonus shifts the safe threshold independently of bust risk, so it stays a
#: distinct axis rather than being folded back into a raw card count; whether
#: x2 is held; a coarse label for the current plus-modifier total). See
#: docs/DECISIONS.md ADR-016: this replaces raw unique_count as the primary
#: axis, which collapsed low-risk and high-risk hands of the same card count
#: into the same cell (ADR-013's addendum).
Cell = tuple[str, bool, bool, str]

UNIQUE_COUNTS: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)

#: Coarse P(bust) buckets (label, inclusive lower bound, exclusive upper
#: bound). Boundaries (10%/27%/40%) were picked from an exhaustive sweep over
#: every possible held-number identity at every unique_count (ADR-016): a
#: bucketed rule crossed with `near_flip7` reproduces the true lookahead_ev
#: hit/stay verdict on ~97% of all such states, against ~82% for the best
#: possible single global P(bust) threshold with no near_flip7 split.
PBUST_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("<10%", 0.00, 0.10),
    ("10-27%", 0.10, 0.27),
    ("27-40%", 0.27, 0.40),
    ("40%+", 0.40, 1.01),
)

#: Coarse plus-total buckets (label, inclusive lower bound, inclusive upper
#: bound). Three buckets, not more: ADR-013 picks this over a finer split so
#: the chart stays a small table a human can memorize, and it lines up with
#: the natural "a +6 or bigger modifier changes my answer" breakpoint that
#: falls out of the generated chart (see docs/DECISIONS.md ADR-013).
PLUS_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("0", 0, 0),
    ("1-5", 1, 5),
    ("6+", 6, 10_000),
)

#: Every (pbust_bucket, near_flip7, has_x2, plus_bucket) cell in chart order.
#: 4 * 2 * 2 * 3 = 48 cells. One cell, ("<10%", True, *, *), is structurally
#: unreachable: the minimum possible P(bust) at unique_count=6 is ~12.7% (the
#: smallest 6 held values are 0-5, all singly-copied or barely-duplicated,
#: but still nonzero) -- kept for grid uniformity, never populated by real
#: samples, and safe on the "stay" fallback since `BasicStrategy.decide` will
#: never actually look it up.
ALL_CELLS: tuple[Cell, ...] = tuple(
    (pbust_bucket[0], near_flip7, has_x2, plus_bucket[0])
    for pbust_bucket, near_flip7, has_x2, plus_bucket in product(
        PBUST_BUCKETS, (False, True), (False, True), PLUS_BUCKETS
    )
)


def p_bust_bucket_label(p: float) -> str:
    """Classify an exact P(bust) fraction into one of `PBUST_BUCKETS`."""
    for label, low, high in PBUST_BUCKETS:
        if low <= p < high:
            return label
    return PBUST_BUCKETS[-1][0]


def _pbust_bucket_bounds(label: str) -> tuple[float, float]:
    for cand_label, low, high in PBUST_BUCKETS:
        if cand_label == label:
            return low, high
    msg = f"unknown p_bust bucket: {label!r}"
    raise ValueError(msg)


def plus_bucket_label(plus_total: int) -> str:
    """Classify a live plus-modifier total into one of `PLUS_BUCKETS`."""
    for label, low, high in PLUS_BUCKETS:
        if low <= plus_total <= high:
            return label
    return PLUS_BUCKETS[-1][0]


def _bucket_bounds(label: str) -> tuple[int, int]:
    for cand_label, low, high in PLUS_BUCKETS:
        if cand_label == label:
            return low, high
    msg = f"unknown plus bucket: {label!r}"
    raise ValueError(msg)


def _sample_held_numbers(rng: Random, unique_count: int) -> list[int]:
    """Pick `unique_count` distinct number values, weighted by deck copies.

    Builds a pool with one entry per physical number card (so value 12, with
    12 copies in the deck, is far more likely to be drawn early than value 0,
    with only 1), shuffles it, and takes the first `unique_count` distinct
    values encountered. This approximates the distribution of "which numbers
    does a player with N unique cards actually tend to hold" without needing
    a full game simulation.
    """
    if unique_count == 0:
        return []
    pool: list[int] = []
    for value, count in NUMBER_COUNTS.items():
        pool.extend([value] * count)
    rng.shuffle(pool)
    chosen: list[int] = []
    seen: set[int] = set()
    for value in pool:
        if value in seen:
            continue
        seen.add(value)
        chosen.append(value)
        if len(chosen) == unique_count:
            break
    return chosen


def _sample_plus_subset(rng: Random, bucket_label: str) -> list[int]:
    """Pick a subset of the 5 plus cards whose sum falls in `bucket_label`.

    Rejection-samples random subsets of `PLUS_VALUES` (only 32 possible) and
    falls back to an exhaustive search over `combinations` if none of the
    random draws land in range (guaranteed to terminate: every bucket in
    `PLUS_BUCKETS` is reachable by at least one subset).
    """
    low, high = _bucket_bounds(bucket_label)
    if low == 0 and high == 0:
        return []
    for _ in range(200):
        subset = [value for value in PLUS_VALUES if rng.random() < 0.5]
        if low <= sum(subset) <= high:
            return subset
    for size in range(len(PLUS_VALUES) + 1):
        for combo in combinations(PLUS_VALUES, size):
            if low <= sum(combo) <= high:
                return list(combo)
    msg = f"no plus-card subset falls in bucket {bucket_label!r}"
    raise RuntimeError(msg)


def _weighted_pool(deck: DeckCounts) -> list[tuple[str, int]]:
    pool: list[tuple[str, int]] = []
    for value, count in deck.numbers.items():
        if count > 0:
            pool.extend([("n", value)] * count)
    for value, count in deck.plus.items():
        if count > 0:
            pool.extend([("p", value)] * count)
    if deck.x2 > 0:
        pool.extend([("x2", 0)] * deck.x2)
    return pool


def _sample_remaining_deck(
    rng: Random,
    held_numbers: list[int],
    held_plus: list[int],
    has_x2: bool,
    *,
    depletion_range: tuple[float, float] = (0.0, 0.6),
) -> DeckCounts:
    """A representative "some cards are already gone" remaining deck.

    Starts from the full deck, removes this player's own held cards, then
    removes a further random fraction (drawn uniformly from
    `depletion_range`) of what's left, weighted by card counts, to stand in
    for cards other seats (or earlier hits by this seat's teammates in the
    same round) have already consumed by the time this decision comes up.
    This is the "Monte Carlo over plausible mid-game remaining decks"
    approach named in the issue, deliberately simpler than replaying full
    games: it does not model *whose* line those depleted cards ended up in,
    only that they are no longer available to draw.
    """
    deck = full_counts()
    for value in held_numbers:
        deck.numbers[value] -= 1
    for value in held_plus:
        deck.plus[value] -= 1
    if has_x2:
        deck.x2 -= 1

    pool = _weighted_pool(deck)
    rng.shuffle(pool)
    fraction = rng.uniform(*depletion_range)
    n_consumed = int(round(fraction * len(pool)))
    for kind, value in pool[:n_consumed]:
        if kind == "n":
            deck.numbers[value] -= 1
        elif kind == "p":
            deck.plus[value] -= 1
        else:
            deck.x2 -= 1
    return deck


def _greedy_held_numbers_for_bucket(
    low: float, high: float, *, require_exact_k: int | None, k_cap: int
) -> list[int]:
    """Deterministic fallback: greedily add the deck's most-duplicated
    values (each addition raises P(bust) fastest, since candidates are
    sorted by descending copy count). If `require_exact_k` is set (the
    `near_flip7` case, which needs exactly that many held numbers), keeps
    adding until reaching it regardless of bucket, since a shorter hand
    would no longer be "one card from Flip 7"; otherwise stops as soon as
    the bucket is entered or `k_cap` is reached. Guaranteed to terminate
    since both bounds are finite.
    """
    candidates = sorted(NUMBER_COUNTS, key=lambda v: -NUMBER_COUNTS[v])
    numbers: list[int] = []
    remaining = full_counts()
    target_k = require_exact_k if require_exact_k is not None else k_cap
    for value in candidates:
        numbers.append(value)
        remaining.numbers[value] -= 1
        reached_target_k = len(numbers) == target_k
        if require_exact_k is not None:
            if reached_target_k:
                break
        elif low <= p_bust(numbers, remaining) < high or reached_target_k:
            break
    return numbers


def _sample_held_and_remaining_for_bucket(
    rng: Random,
    pbust_label: str,
    near_flip7: bool,
    plus_cards: list[int],
    has_x2: bool,
    *,
    max_attempts: int = 300,
) -> tuple[list[int], DeckCounts]:
    """Sample held numbers + a remaining deck whose exact P(bust) lands in
    `pbust_label`'s bucket, rejection-sampling first and falling back to a
    deterministic greedy search (guaranteed to terminate) if none of the
    random draws land in range -- the same shape as `_sample_plus_subset`.
    """
    low, high = _pbust_bucket_bounds(pbust_label)
    for _ in range(max_attempts):
        k = 6 if near_flip7 else rng.randint(0, 5)
        numbers = _sample_held_numbers(rng, k)
        remaining = _sample_remaining_deck(rng, numbers, plus_cards, has_x2)
        if low <= p_bust(numbers, remaining) < high:
            return numbers, remaining
    numbers = _greedy_held_numbers_for_bucket(
        low, high, require_exact_k=6 if near_flip7 else None, k_cap=5
    )
    remaining = _sample_remaining_deck(rng, numbers, plus_cards, has_x2)
    return numbers, remaining


def _cache_key(
    numbers: list[int], plus_total: int, has_x2: bool, remaining: DeckCounts
) -> tuple[object, ...]:
    return (
        tuple(sorted(numbers)),
        plus_total,
        has_x2,
        tuple(sorted(remaining.numbers.items())),
        tuple(sorted(remaining.plus.items())),
        remaining.x2,
    )


@dataclass
class CellStats:
    """Aggregated `lookahead_ev` verdict for one chart cell."""

    cell: Cell
    samples: int
    hit_votes: int
    mean_hit_ev: float
    mean_stay_value: float
    recommendation: str

    @property
    def hit_fraction(self) -> float:
        return self.hit_votes / self.samples if self.samples else 0.0

    @property
    def mean_ev_gap(self) -> float:
        """Mean(hit EV - stay value) across samples; the chart's per-cell edge."""
        return self.mean_hit_ev - self.mean_stay_value


def evaluate_cell(
    rng: Random,
    cell: Cell,
    samples_per_cell: int,
    cache: dict[tuple[object, ...], float],
) -> CellStats:
    """Average `lookahead_ev`'s hit/stay verdict over `samples_per_cell` decks.

    A representative sample is drawn fresh each time (see
    `_sample_held_and_remaining_for_bucket`/`_sample_plus_subset`); `cache`
    memoizes `lookahead_ev` itself (keyed on a hashable reduction of its
    inputs, per `_cache_key`) so repeated samples that happen to land on the
    same effective state -- common for small/empty cells -- are not
    recomputed.
    """
    pbust_bucket, near_flip7, has_x2, bucket_label = cell
    hit_votes = 0
    hit_ev_sum = 0.0
    stay_sum = 0.0
    for _ in range(samples_per_cell):
        plus_cards = _sample_plus_subset(rng, bucket_label)
        plus_total = sum(plus_cards)
        numbers, remaining = _sample_held_and_remaining_for_bucket(
            rng, pbust_bucket, near_flip7, plus_cards, has_x2
        )

        key = _cache_key(numbers, plus_total, has_x2, remaining)
        hit_ev = cache.get(key)
        if hit_ev is None:
            hit_ev = lookahead_ev(numbers, plus_total, has_x2, remaining)
            cache[key] = hit_ev

        stay_value = float(score_line(numbers, plus_total, has_x2, False))
        hit_ev_sum += hit_ev
        stay_sum += stay_value
        if hit_ev > stay_value:
            hit_votes += 1

    recommendation = "hit" if hit_votes * 2 >= samples_per_cell else "stay"
    return CellStats(
        cell=cell,
        samples=samples_per_cell,
        hit_votes=hit_votes,
        mean_hit_ev=hit_ev_sum / samples_per_cell,
        mean_stay_value=stay_sum / samples_per_cell,
        recommendation=recommendation,
    )


@dataclass
class BasicStrategyTable:
    """A full chart: one `CellStats` per `Cell`, plus the generation params."""

    seed: int
    samples_per_cell: int
    cells: dict[Cell, CellStats] = field(default_factory=dict)

    def chart(self) -> dict[Cell, str]:
        """`{cell: "hit" | "stay"}` -- the memorizable part of the table."""
        return {cell: stats.recommendation for cell, stats in self.cells.items()}

    def recommend(
        self, numbers: list[int], has_x2: bool, plus_total: int, remaining: DeckCounts
    ) -> str:
        cell: Cell = (
            p_bust_bucket_label(p_bust(numbers, remaining)),
            len(numbers) == 6,
            has_x2,
            plus_bucket_label(plus_total),
        )
        stats = self.cells.get(cell)
        return stats.recommendation if stats is not None else "stay"


def generate_basic_strategy_table(
    seed: int,
    samples_per_cell: int = 6,
    cells: Sequence[Cell] | None = None,
) -> BasicStrategyTable:
    """Distill `lookahead_ev` into a small hit/stay chart (ADR-013, ADR-016).

    Deterministic in `seed`: a fixed `Random(seed)` is consumed in a fixed
    order (chart-row order over `ALL_CELLS`, or the caller's `cells`), so the
    same seed always produces the same chart.
    """
    rng = Random(seed)
    target_cells = tuple(cells) if cells is not None else ALL_CELLS
    cache: dict[tuple[object, ...], float] = {}
    results: dict[Cell, CellStats] = {}
    for cell in target_cells:
        results[cell] = evaluate_cell(rng, cell, samples_per_cell, cache)
    return BasicStrategyTable(seed=seed, samples_per_cell=samples_per_cell, cells=results)
