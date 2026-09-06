from __future__ import annotations

from flip7.engine import TableView
from flip7.probability import DeckCounts, full_counts
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
    chart = {("<10%", False, False, "0"): "hit", ("40%+", False, False, "0"): "stay"}
    policy = BasicStrategy(chart)
    remaining = DeckCounts(numbers={9: 5}, plus={}, x2=0)

    # Held value absent from the remaining deck: P(bust)=0.
    hit_line = PlayerLine(numbers=[1])
    assert policy.decide(_view(hit_line, remaining)) == "hit"

    # Held value is all that's left in the remaining deck: P(bust)=1.0.
    stay_line = PlayerLine(numbers=[9])
    assert policy.decide(_view(stay_line, remaining)) == "stay"


def test_basic_strategy_classifies_plus_bucket_and_near_flip7_correctly() -> None:
    chart = {("40%+", False, True, "6+"): "hit"}
    policy = BasicStrategy(chart)
    remaining = DeckCounts(numbers={5: 5}, plus={}, x2=0)
    # 8 unique cards can't occur mid-decision (Flip 7 ends the round at 7),
    # but decide() should never KeyError -- it falls back to "stay" via
    # dict.get, same as any other uncharted cell. near_flip7 requires
    # *exactly* 6 held numbers, so this (8) does not qualify; P(bust) is
    # still exact (5/5 = 1.0, all that's left is the held value 5); plus=100
    # classifies into the "6+" bucket.
    line = PlayerLine(numbers=[0, 1, 2, 3, 5, 6, 7, 8], plus=100, has_x2=True)
    assert policy.decide(_view(line, remaining)) == "hit"


def test_basic_strategy_defaults_to_stay_for_an_uncharted_cell() -> None:
    policy = BasicStrategy({})
    remaining = DeckCounts(numbers={}, plus={}, x2=0)
    line = PlayerLine(numbers=[1, 2])
    assert policy.decide(_view(line, remaining)) == "stay"


def test_basic_strategy_default_chart_hits_with_an_empty_hand() -> None:
    policy = BasicStrategy()
    remaining = DeckCounts(numbers={1: 5}, plus={}, x2=0)
    line = PlayerLine(numbers=[])
    assert policy.decide(_view(line, remaining)) == "hit"


def test_basic_strategy_hits_a_low_value_hand_but_stays_on_a_high_value_hand() -> None:
    # The exact blind spot ADR-013's addendum found and ADR-016 fixes: raw
    # card count alone can't distinguish these two hands (6 held numbers vs.
    # 4), but the shipped chart's P(bust) axis does -- {0..5} is one card
    # from Flip 7 with low bust risk (P(bust)=12.7%, hit), {12,11,10,9} is
    # only 4 cards but high bust risk (P(bust)=46.9%, stay). Both margins are
    # comfortably clear of the true hit/stay boundary (~27%/~40%), unlike a
    # 2-card high-value hand, which lands right at an exact EV tie.
    policy = BasicStrategy()

    low_numbers = [0, 1, 2, 3, 4, 5]
    low_remaining = full_counts()
    for value in low_numbers:
        low_remaining.numbers[value] -= 1
    low_line = PlayerLine(numbers=low_numbers)
    assert policy.decide(_view(low_line, low_remaining)) == "hit"

    high_numbers = [12, 11, 10, 9]
    high_remaining = full_counts()
    for value in high_numbers:
        high_remaining.numbers[value] -= 1
    high_line = PlayerLine(numbers=high_numbers)
    assert policy.decide(_view(high_line, high_remaining)) == "stay"


def test_basic_strategy_registered_in_named_policies() -> None:
    policies = named_policies()
    assert "basic_strategy" in policies
    assert isinstance(policies["basic_strategy"], BasicStrategy)


def test_basic_strategy_chart_constant_covers_the_full_grid() -> None:
    from flip7.basic_strategy import ALL_CELLS

    assert set(BASIC_STRATEGY_CHART) == set(ALL_CELLS)
    assert set(BASIC_STRATEGY_CHART.values()) <= {"hit", "stay"}
