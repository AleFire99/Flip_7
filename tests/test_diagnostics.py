from __future__ import annotations

import random

from flip7.cards import number_card
from flip7.diagnostics import DiagnosticsReport, process_trace, run_diagnostics
from flip7.engine import TraceEvent, play_round
from flip7.strategy import StayAfterDeal


class Scripted:
    name = "scripted"

    def __init__(self, moves: list[str]) -> None:
        self._moves = list(moves)

    def decide(self, view: object) -> str:
        if not self._moves:
            return "stay"
        return self._moves.pop(0)


def _pile(*cards: object) -> list:  # type: ignore[type-arg]
    """First argument is dealt first (engine pops from the end)."""
    return list(reversed(cards))


def _empty_report() -> DiagnosticsReport:
    return DiagnosticsReport(policy_name="test", n_games=1, n_players=2, seed=0)


def test_process_trace_records_a_bust_by_unique_count_round_and_value() -> None:
    deck = _pile(number_card(3), number_card(5), number_card(3))
    trace: list[TraceEvent] = []
    play_round(
        [Scripted(["hit"]), Scripted(["stay"])],
        random.Random(0),
        deck=deck,
        trace=trace,
        round_no=1,
    )
    report = _empty_report()
    process_trace(report, trace)

    # Both seats hold 1 unique number at decision time (seat 0 dealt a 3,
    # seat 1 dealt a 5), so they land in the same cell: 1 hit (seat 0) out
    # of 2 total decisions (seat 0 hits, seat 1 stays).
    assert report.decisions[(1, False, "0")] == [1, 2]
    # Only seat 0's hit draws a card (a duplicate 3 -> bust); seat 1's stay
    # never enters the bust-rate breakdowns at all.
    assert report.bust_by_unique_count[1] == [1, 1]
    assert report.bust_by_round[1] == [1, 1]
    assert report.bust_by_value[3] == [1, 1]


def test_process_trace_records_stay_decisions_without_a_bust_entry() -> None:
    deck = _pile(number_card(4), number_card(5))
    trace: list[TraceEvent] = []
    play_round(
        [Scripted(["stay"]), Scripted(["stay"])],
        random.Random(0),
        deck=deck,
        trace=trace,
        round_no=1,
    )
    report = _empty_report()
    process_trace(report, trace)

    assert report.decisions[(1, False, "0")] == [0, 2]  # 0 hits out of 2 decisions
    assert report.bust_by_unique_count == {}
    assert report.bust_by_round == {}
    assert report.bust_by_value == {}


def test_process_trace_ignores_a_non_number_draw_for_bust_by_value() -> None:
    # seat 0 hits and draws a +2 modifier: never busts, and isn't a number
    # value, so it should count toward the unique_count/round breakdowns
    # (a real hit *attempt* that happened not to risk a bust) but not
    # bust_by_value (no number was drawn).
    from flip7.cards import plus_card

    deck = _pile(number_card(3), number_card(5), plus_card(2))
    trace: list[TraceEvent] = []
    play_round(
        [Scripted(["hit"]), Scripted(["stay"])],
        random.Random(0),
        deck=deck,
        trace=trace,
        round_no=1,
    )
    report = _empty_report()
    process_trace(report, trace)

    assert report.bust_by_unique_count[1] == [0, 1]
    assert report.bust_by_round[1] == [0, 1]
    assert report.bust_by_value == {}


def test_run_diagnostics_produces_a_score_distribution_and_decision_chart() -> None:
    report = run_diagnostics(
        StayAfterDeal(),
        "stay_after_deal",
        n_players=3,
        n_games=5,
        seed=1,
        target=30,
        max_rounds=3,
    )
    assert len(report.totals) == 15  # 5 games x 3 seats

    total_hits = sum(hits for hits, _ in report.decisions.values())
    total_decisions = sum(total for _, total in report.decisions.values())
    # stay_after_deal always stays right after the initial deal.
    assert total_hits == 0
    assert total_decisions > 0
    # A policy that never hits never busts.
    assert report.bust_by_unique_count == {}
    assert report.bust_by_round == {}
    assert report.bust_by_value == {}
