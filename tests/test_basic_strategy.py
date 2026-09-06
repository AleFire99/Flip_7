from __future__ import annotations

from flip7.basic_strategy import (
    ALL_CELLS,
    PLUS_BUCKETS,
    UNIQUE_COUNTS,
    generate_basic_strategy_table,
    plus_bucket_label,
)


def test_all_cells_cover_the_expected_grid() -> None:
    assert len(ALL_CELLS) == len(UNIQUE_COUNTS) * 2 * len(PLUS_BUCKETS)
    assert len(set(ALL_CELLS)) == len(ALL_CELLS)


def test_plus_bucket_label_boundaries() -> None:
    assert plus_bucket_label(0) == "0"
    assert plus_bucket_label(1) == "1-5"
    assert plus_bucket_label(5) == "1-5"
    assert plus_bucket_label(6) == "6+"
    assert plus_bucket_label(30) == "6+"


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


def test_empty_hand_always_recommends_hit() -> None:
    # With zero unique cards held, every deck sample is safe from an
    # immediate bust: hitting can never be worse than staying at 0.
    cells = [(0, has_x2, bucket[0]) for has_x2 in (False, True) for bucket in PLUS_BUCKETS]
    table = generate_basic_strategy_table(seed=3, samples_per_cell=3, cells=cells)
    for cell in cells:
        assert table.cells[cell].recommendation == "hit"


def test_six_unique_cards_always_recommends_stay() -> None:
    # One card away from Flip 7: any remaining safe number ends the round for
    # a modest +15, but the bust risk from the other ~11 held-adjacent values
    # dominates against a representative mid-game deck.
    cells = [(6, has_x2, bucket[0]) for has_x2 in (False, True) for bucket in PLUS_BUCKETS]
    table = generate_basic_strategy_table(seed=3, samples_per_cell=6, cells=cells)
    for cell in cells:
        assert table.cells[cell].recommendation == "stay"


def test_recommend_clamps_unique_count_and_buckets_plus_total() -> None:
    table = generate_basic_strategy_table(
        seed=1, samples_per_cell=1, cells=[(6, False, "6+")]
    )
    # unique_count above 6 (shouldn't occur mid-decision, but recommend()
    # should not KeyError) clamps down to the charted 6-card cell.
    assert table.recommend(9, False, 100) == table.cells[(6, False, "6+")].recommendation


def test_recommend_falls_back_to_stay_for_an_uncharted_cell() -> None:
    table = generate_basic_strategy_table(seed=1, samples_per_cell=1, cells=[(0, False, "0")])
    assert table.recommend(3, True, 2) == "stay"
