from __future__ import annotations

from flip7.basic_strategy import (
    ALL_CELLS,
    HELD_VALUE_SUM_STAY_THRESHOLDS,
    PBUST_BUCKETS,
    PLUS_BUCKETS,
    generate_basic_strategy_table,
    p_bust_bucket_label,
    plus_bucket_label,
    tally_recommend,
)
from flip7.probability import DeckCounts, full_counts, lookahead_ev, p_bust
from flip7.scoring import score_line


def test_all_cells_cover_the_expected_grid() -> None:
    assert len(ALL_CELLS) == len(PBUST_BUCKETS) * 2 * 2 * len(PLUS_BUCKETS)
    assert len(set(ALL_CELLS)) == len(ALL_CELLS)


def test_plus_bucket_label_boundaries() -> None:
    assert plus_bucket_label(0) == "0"
    assert plus_bucket_label(1) == "1-5"
    assert plus_bucket_label(5) == "1-5"
    assert plus_bucket_label(6) == "6+"
    assert plus_bucket_label(30) == "6+"


def test_p_bust_bucket_label_boundaries() -> None:
    assert p_bust_bucket_label(0.0) == "<10%"
    assert p_bust_bucket_label(0.099) == "<10%"
    assert p_bust_bucket_label(0.10) == "10-27%"
    assert p_bust_bucket_label(0.269) == "10-27%"
    assert p_bust_bucket_label(0.27) == "27-40%"
    assert p_bust_bucket_label(0.399) == "27-40%"
    assert p_bust_bucket_label(0.40) == "40%+"
    assert p_bust_bucket_label(1.0) == "40%+"


def test_generate_basic_strategy_table_is_deterministic_for_a_seed() -> None:
    cells = ALL_CELLS[:6]
    first = generate_basic_strategy_table(seed=7, samples_per_cell=2, cells=cells)
    second = generate_basic_strategy_table(seed=7, samples_per_cell=2, cells=cells)
    assert first.chart() == second.chart()
    for cell in cells:
        assert first.cells[cell].mean_hit_ev == second.cells[cell].mean_hit_ev
        assert first.cells[cell].mean_stay_value == second.cells[cell].mean_stay_value


def test_generate_basic_strategy_table_can_differ_across_seeds() -> None:
    cells = ALL_CELLS[:6]
    a = generate_basic_strategy_table(seed=1, samples_per_cell=2, cells=cells)
    b = generate_basic_strategy_table(seed=2, samples_per_cell=2, cells=cells)
    # Not asserting the recommendations differ (small samples could agree by
    # chance), but the underlying sampled EVs should not be identical.
    assert any(
        a.cells[cell].mean_hit_ev != b.cells[cell].mean_hit_ev for cell in cells
    )


def test_lowest_pbust_bucket_always_recommends_hit() -> None:
    # <10% P(bust) covers a mix of unique_counts (an empty hand, or a few
    # low-duplication values like {0, 1}) -- deliberately merging them under
    # the new axis, unlike the old count-only chart. Every true hit/stay
    # boundary observed across the whole state space sits at P(bust) well
    # above 10%, so this bucket should always recommend hit.
    cells = [
        ("<10%", False, has_x2, bucket[0]) for has_x2 in (False, True) for bucket in PLUS_BUCKETS
    ]
    table = generate_basic_strategy_table(seed=3, samples_per_cell=3, cells=cells)
    for cell in cells:
        assert table.cells[cell].recommendation == "hit"


def test_low_held_values_at_six_unique_cards_are_an_exact_hit() -> None:
    # ADR-013's addendum, reproduced directly (exact, not sampled): held
    # numbers {0..5} at unique_count=6 (one card from Flip 7) has an exact
    # P(bust) of ~12.7%, and the true lookahead_ev verdict is "hit" -- the
    # exact opposite of the old count-only chart's blanket "stay at 6 cards"
    # rule. (Not asserted via the Monte Carlo table generator: has_x2/plus
    # combinations at the edge of a bucket can shift the sampled majority
    # vote even where the plus=0/no-x2 baseline is unambiguous.)
    numbers = [0, 1, 2, 3, 4, 5]
    remaining = full_counts()
    for value in numbers:
        remaining.numbers[value] -= 1
    assert p_bust_bucket_label(p_bust(numbers, remaining)) == "10-27%"
    hit_ev = lookahead_ev(numbers, 0, False, remaining)
    stay_value = float(score_line(numbers, 0, False, False))
    assert hit_ev > stay_value


def test_highest_pbust_bucket_always_recommends_stay() -> None:
    # 40%+ P(bust) sits well past every true-hit case observed across the
    # full state space (max ~40% at unique_count=6, lower still at smaller
    # counts), regardless of card count -- unlike the old count-only chart,
    # which would force "hit" on any such hand at unique_count <= 2.
    cells = [
        ("40%+", near_flip7, has_x2, plus[0])
        for near_flip7 in (False, True)
        for has_x2 in (False, True)
        for plus in PLUS_BUCKETS
    ]
    table = generate_basic_strategy_table(seed=3, samples_per_cell=6, cells=cells)
    for cell in cells:
        assert table.cells[cell].recommendation == "stay"


def test_recommend_uses_exact_p_bust_and_near_flip7() -> None:
    table = generate_basic_strategy_table(
        seed=1, samples_per_cell=1, cells=[("<10%", False, False, "6+")]
    )
    remaining = DeckCounts(numbers={11: 5}, plus={}, x2=0)
    # A single held low-duplication number against a deck with none of it
    # left: P(bust)=0, near_flip7=False -> ("<10%", False, False, "6+").
    assert table.recommend([1], False, 100, remaining) == table.cells[
        ("<10%", False, False, "6+")
    ].recommendation


def test_unreachable_near_flip7_low_pbust_cell_resolves_to_hit() -> None:
    # ("<10%", True, *, *) is structurally unreachable (min P(bust) at
    # unique_count=6 is ~12.7%), so the sampler always falls back to the
    # closest achievable state -- the 6 least-duplicated values {0..5} --
    # whose true verdict is "hit". It should read "hit", not an arbitrary
    # extreme like the 6 most-duplicated values (whose true verdict would
    # be "stay").
    cell = ("<10%", True, False, "0")
    table = generate_basic_strategy_table(seed=5, samples_per_cell=6, cells=[cell])
    assert table.cells[cell].recommendation == "hit"


def test_tally_recommend_matches_the_documented_thresholds() -> None:
    assert tally_recommend(0, 0) == "hit"
    assert tally_recommend(1, 12) == "hit"
    assert tally_recommend(2, 22) == "hit"
    assert tally_recommend(2, 23) == "stay"
    assert tally_recommend(6, 35) == "hit"
    assert tally_recommend(6, 36) == "stay"


def test_held_value_sum_thresholds_cover_every_unique_count() -> None:
    assert set(HELD_VALUE_SUM_STAY_THRESHOLDS) == set(range(7))


def test_recommend_falls_back_to_stay_for_an_uncharted_cell() -> None:
    table = generate_basic_strategy_table(
        seed=1, samples_per_cell=1, cells=[("<10%", False, False, "0")]
    )
    remaining = DeckCounts(numbers={12: 12}, plus={}, x2=0)
    # Held [12] against a full 12-count remaining: P(bust) is well above
    # 40%, landing in a cell this table never generated.
    assert table.recommend([12], True, 2, remaining) == "stay"
