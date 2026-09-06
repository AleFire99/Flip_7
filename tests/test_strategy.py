from __future__ import annotations

from flip7.engine import TableView
from flip7.probability import DeckCounts
from flip7.state import PlayerLine
from flip7.strategy import (
    BASIC_STRATEGY_CHART,
    BasicStrategy,
    LookaheadEV,
    OneStepEV,
    named_policies,
)


def _view(line: PlayerLine, remaining: DeckCounts) -> TableView:
    return TableView(
        lines=(line,),
        remaining=remaining,
        totals=(0,),
        dealer=0,
        acting=0,
    )


def test_lookahead_ev_hits_on_a_safe_deck() -> None:
    line = PlayerLine(numbers=[1, 2])
    # Single card left, cannot bust and cannot lower the line: must hit.
    remaining = DeckCounts(numbers={11: 1}, plus={}, x2=0)
    assert LookaheadEV().decide(_view(line, remaining)) == "hit"


def test_lookahead_ev_stays_with_nothing_left_to_draw() -> None:
    line = PlayerLine(numbers=[1, 2], plus=4)
    remaining = DeckCounts(numbers={}, plus={}, x2=0)
    assert LookaheadEV().decide(_view(line, remaining)) == "stay"


def test_lookahead_ev_stays_when_busted() -> None:
    line = PlayerLine(numbers=[1, 2], busted=True)
    remaining = DeckCounts(numbers={11: 1}, plus={}, x2=0)
    assert LookaheadEV().decide(_view(line, remaining)) == "stay"


def test_lookahead_ev_never_more_cautious_than_one_step_ev() -> None:
    # A deck where the next card is very likely to bust, so one-step EV
    # already says stay; the DP policy (which sees further ahead but is
    # never worse-informed) must agree it isn't worth hitting either.
    line = PlayerLine(numbers=[5, 9, 3])
    remaining = DeckCounts(numbers={5: 3, 9: 2}, plus={}, x2=0)
    view = _view(line, remaining)
    assert OneStepEV().decide(view) == "stay"
    assert LookaheadEV().decide(view) == "stay"


def test_lookahead_ev_registered_in_named_policies() -> None:
    policies = named_policies()
    assert "lookahead_ev" in policies
    assert isinstance(policies["lookahead_ev"], LookaheadEV)


def test_basic_strategy_reads_the_chart_for_its_cell() -> None:
    chart = {(2, False, "0"): "hit", (3, False, "0"): "stay"}
    policy = BasicStrategy(chart)
    remaining = DeckCounts(numbers={1: 5}, plus={}, x2=0)

    hit_line = PlayerLine(numbers=[1, 2])
    assert policy.decide(_view(hit_line, remaining)) == "hit"

    stay_line = PlayerLine(numbers=[1, 2, 3])
    assert policy.decide(_view(stay_line, remaining)) == "stay"


def test_basic_strategy_caps_unique_count_and_buckets_plus_total() -> None:
    chart = {(6, True, "6+"): "hit"}
    policy = BasicStrategy(chart)
    remaining = DeckCounts(numbers={}, plus={}, x2=0)
    # 8 unique cards can't occur mid-decision (Flip 7 ends the round at 7),
    # but decide() should clamp rather than KeyError; plus=100 should
    # classify into the "6+" bucket, not fail to match.
    line = PlayerLine(numbers=[0, 1, 2, 3, 4, 5, 6, 7], plus=100, has_x2=True)
    assert policy.decide(_view(line, remaining)) == "hit"


def test_basic_strategy_defaults_to_stay_for_an_uncharted_cell() -> None:
    policy = BasicStrategy({})
    remaining = DeckCounts(numbers={}, plus={}, x2=0)
    line = PlayerLine(numbers=[1, 2])
    assert policy.decide(_view(line, remaining)) == "stay"


def test_basic_strategy_default_chart_hits_below_three_cards() -> None:
    policy = BasicStrategy()
    remaining = DeckCounts(numbers={1: 5}, plus={}, x2=0)
    for count in (0, 1, 2):
        line = PlayerLine(numbers=list(range(count)))
        assert policy.decide(_view(line, remaining)) == "hit", count


def test_basic_strategy_registered_in_named_policies() -> None:
    policies = named_policies()
    assert "basic_strategy" in policies
    assert isinstance(policies["basic_strategy"], BasicStrategy)


def test_basic_strategy_chart_constant_covers_the_full_grid() -> None:
    from flip7.basic_strategy import ALL_CELLS

    assert set(BASIC_STRATEGY_CHART) == set(ALL_CELLS)
    assert set(BASIC_STRATEGY_CHART.values()) <= {"hit", "stay"}
