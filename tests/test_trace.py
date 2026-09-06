from __future__ import annotations

import random

from flip7.cards import flip_three_card, freeze_card, number_card, plus_card
from flip7.engine import TraceEvent, play_game, play_round
from flip7.strategy import StayAfterDeal


class Scripted:
    name = "scripted"

    def __init__(self, moves: list[str]) -> None:
        self._moves = list(moves)

    def decide(self, view: object) -> str:
        if not self._moves:
            return "stay"
        return self._moves.pop(0)


class ScriptedTargeting(Scripted):
    def __init__(self, moves: list[str], target: int) -> None:
        super().__init__(moves)
        self.target = target

    def choose_target(self, view: object, card: object, candidates: tuple[int, ...]) -> int:
        return self.target


def _pile(*cards: object) -> list:  # type: ignore[type-arg]
    return list(reversed(cards))


def test_trace_defaults_to_none_and_does_not_affect_result() -> None:
    deck = _pile(number_card(1), number_card(2), number_card(3))
    result = play_round(
        [Scripted(["stay"]), Scripted(["stay"]), Scripted(["stay"])],
        random.Random(0),
        deck=deck,
    )
    assert result.scores == [1, 2, 3]


def test_trace_records_deal_and_hit_events() -> None:
    deck = _pile(number_card(1), number_card(2), number_card(7))
    trace: list[TraceEvent] = []
    result = play_round(
        [Scripted(["stay"]), Scripted(["hit"])],
        random.Random(0),
        deck=deck,
        trace=trace,
    )
    assert result.scores == [1, 2 + 7]
    deals = [e for e in trace if e.kind == "deal"]
    assert [(e.seat, e.card, e.outcome) for e in deals] == [
        (0, "1", "ok"),
        (1, "2", "ok"),
    ]
    hits = [e for e in trace if e.kind == "hit"]
    # seat 0 stays without drawing, seat 1 hits and draws the 7
    assert any(e.seat == 0 and e.card is None and e.outcome == "stay" for e in hits)
    assert any(e.seat == 1 and e.card == "7" and e.outcome == "ok" for e in hits)


def test_trace_records_freeze_with_default_targeting() -> None:
    deck = _pile(number_card(1), number_card(2), number_card(3), freeze_card())
    trace: list[TraceEvent] = []
    play_round(
        [Scripted(["hit"]), Scripted(["hit"]), Scripted(["stay"])],
        random.Random(0),
        deck=deck,
        trace=trace,
    )
    freeze_events = [e for e in trace if e.card == "Freeze"]
    assert len(freeze_events) == 1
    event = freeze_events[0]
    assert event.seat == 0
    assert event.target == 1
    assert event.target_via == "default"


def test_trace_records_freeze_with_policy_targeting() -> None:
    deck = _pile(
        number_card(1),
        number_card(2),
        number_card(3),
        number_card(4),
        freeze_card(),
        plus_card(2),
        plus_card(4),
    )
    trace: list[TraceEvent] = []
    play_round(
        [
            ScriptedTargeting(["hit"], target=3),
            Scripted(["hit", "hit"]),
            Scripted(["stay"]),
            Scripted(["hit"]),
        ],
        random.Random(0),
        deck=deck,
        trace=trace,
    )
    freeze_events = [e for e in trace if e.card == "Freeze"]
    assert len(freeze_events) == 1
    event = freeze_events[0]
    assert event.target == 3
    assert event.target_via == "policy"


def test_trace_records_flip_three_and_forced_draws() -> None:
    deck = _pile(
        number_card(9),
        number_card(5),
        flip_three_card(),
        number_card(6),
        number_card(5),  # duplicate -> bust, 3rd forced draw skipped
    )
    trace: list[TraceEvent] = []
    result = play_round(
        [Scripted(["hit"]), Scripted(["hit"])],
        random.Random(0),
        deck=deck,
        trace=trace,
    )
    assert result.lines[1].busted is True
    flip_three_events = [e for e in trace if e.card == "Flip Three"]
    assert len(flip_three_events) == 1
    assert flip_three_events[0].seat == 0
    assert flip_three_events[0].target == 1
    assert flip_three_events[0].target_via == "default"
    # the two forced draws against seat 1 are recorded in order, tagged with
    # the same phase ("hit") as the Flip Three draw that triggered them --
    # excluding seat 1's own initial "deal" of a 5, which predates the
    # Flip Three and would otherwise also match on card label.
    forced = [e for e in trace if e.seat == 1 and e.kind == "hit"]
    assert [(e.card, e.outcome) for e in forced] == [("6", "ok"), ("5", "bust")]


def test_play_game_can_use_the_94_card_action_card_deck_and_trace() -> None:
    trace: list[TraceEvent] = []
    result = play_game(
        [StayAfterDeal(), StayAfterDeal(), StayAfterDeal()],
        random.Random(1),
        target=50,
        max_rounds=5,
        use_action_cards=True,
        trace=trace,
    )
    assert result.rounds >= 1
    assert any(e.kind == "round_start" for e in trace)
    assert any(e.kind == "round_end" for e in trace)
    assert any(e.kind == "deal" for e in trace)
