from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import combinations, product
from random import Random

from flip7.cards import NUMBER_COUNTS, PLUS_VALUES
from flip7.probability import DeckCounts, full_counts, lookahead_ev
from flip7.scoring import score_line

#: A chartable state: (unique number cards held, capped at 6; whether x2 is
#: held; a coarse label for the current plus-modifier total). Flip 7 (7
#: unique numbers) never reaches a hit/stay decision -- the round already
#: ended -- so 6 is the largest chartable count.
Cell = tuple[int, bool, str]

UNIQUE_COUNTS: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)

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

#: Every (unique_count, has_x2, plus_bucket) cell in chart order: rows first
#: by unique_count, then has_x2, then plus bucket. 7 * 2 * 3 = 42 cells.
ALL_CELLS: tuple[Cell, ...] = tuple(
    (unique_count, has_x2, bucket[0])
    for unique_count, has_x2, bucket in product(UNIQUE_COUNTS, (False, True), PLUS_BUCKETS)
)


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
    `_sample_held_numbers`/`_sample_plus_subset`/`_sample_remaining_deck`);
    `cache` memoizes `lookahead_ev` itself (keyed on a hashable reduction of
    its inputs, per `_cache_key`) so repeated samples that happen to land on
    the same effective state -- common for small/empty cells such as
    unique_count=0 -- are not recomputed.
    """
    unique_count, has_x2, bucket_label = cell
    hit_votes = 0
    hit_ev_sum = 0.0
    stay_sum = 0.0
    for _ in range(samples_per_cell):
        numbers = _sample_held_numbers(rng, unique_count)
        plus_cards = _sample_plus_subset(rng, bucket_label)
        plus_total = sum(plus_cards)
        remaining = _sample_remaining_deck(rng, numbers, plus_cards, has_x2)

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

    def recommend(self, unique_count: int, has_x2: bool, plus_total: int) -> str:
        cell = (min(unique_count, 6), has_x2, plus_bucket_label(plus_total))
        stats = self.cells.get(cell)
        return stats.recommendation if stats is not None else "stay"


def generate_basic_strategy_table(
    seed: int,
    samples_per_cell: int = 6,
    cells: Sequence[Cell] | None = None,
) -> BasicStrategyTable:
    """Distill `lookahead_ev` into a small hit/stay chart (ADR-013).

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
