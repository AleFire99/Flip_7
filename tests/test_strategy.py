from __future__ import annotations

from flip7.engine import TableView
from flip7.probability import DeckCounts
from flip7.state import PlayerLine
from flip7.strategy import LookaheadEV, OneStepEV, named_policies


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
