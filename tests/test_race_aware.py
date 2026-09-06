from __future__ import annotations

from flip7.cards import flip_three_card, freeze_card
from flip7.engine import TableView
from flip7.probability import DeckCounts
from flip7.state import PlayerLine
from flip7.strategy import LookaheadEV, RaceAwareEV, named_policies


def _view(
    lines: list[PlayerLine],
    remaining: DeckCounts,
    totals: list[int],
    acting: int,
) -> TableView:
    return TableView(
        lines=tuple(lines),
        remaining=remaining,
        totals=tuple(totals),
        dealer=0,
        acting=acting,
    )


def test_race_aware_ev_registered_in_named_policies() -> None:
    policies = named_policies()
    assert "race_aware_ev" in policies
    assert isinstance(policies["race_aware_ev"], RaceAwareEV)


def test_race_aware_ev_hits_to_catch_up_when_opponent_threatens_flip7() -> None:
    # Opponent is one card from Flip 7 (round could end any moment) and is
    # already ahead on projected total. LookaheadEV, opponent-blind, only
    # sees a mildly bad hit EV (9.0) below the current score (10) and stays.
    # RaceAwareEV adds a catch-up bonus scaled to the deficit and hits instead.
    me = PlayerLine(numbers=[10])
    opponent = PlayerLine(numbers=[0, 1, 2, 3, 4, 5])
    remaining = DeckCounts(numbers={10: 1}, plus={8: 1}, x2=0)
    view = _view([me, opponent], remaining, totals=[0, 5], acting=0)

    assert LookaheadEV().decide(view) == "stay"
    assert RaceAwareEV().decide(view) == "hit"


def test_race_aware_ev_stays_to_protect_a_lead_when_opponent_threatens_flip7() -> None:
    # Opponent is one card from Flip 7 again, but this time the acting seat
    # is already comfortably ahead on projected total. LookaheadEV sees a
    # guaranteed small gain from hitting (a deterministic +2 card) and hits.
    # RaceAwareEV subtracts a lead-protection margin and banks the lead instead.
    me = PlayerLine(numbers=[3])
    opponent = PlayerLine(numbers=[0, 1, 2, 3, 4, 5])
    remaining = DeckCounts(numbers={}, plus={2: 1}, x2=0)
    view = _view([me, opponent], remaining, totals=[20, 0], acting=0)

    assert LookaheadEV().decide(view) == "hit"
    assert RaceAwareEV().decide(view) == "stay"


def test_race_aware_ev_matches_lookahead_ev_absent_any_threat() -> None:
    # No opponent is near Flip 7 or near 200: no threat signal, so the race
    # adjustment is a no-op and RaceAwareEV agrees with plain LookaheadEV.
    me = PlayerLine(numbers=[3])
    opponent = PlayerLine(numbers=[1, 2])
    remaining = DeckCounts(numbers={}, plus={2: 1}, x2=0)
    view = _view([me, opponent], remaining, totals=[20, 0], acting=0)

    assert LookaheadEV().decide(view) == RaceAwareEV().decide(view) == "hit"


def test_race_aware_ev_hits_when_opponent_already_past_target() -> None:
    # Opponent's projected total (banked total + current partial line) is
    # already at/over TARGET_SCORE: they're positioned to win outright once
    # the round ends, even with no Flip 7 threat. That alone is enough to
    # trigger the catch-up bonus.
    me = PlayerLine(numbers=[10])
    opponent = PlayerLine(numbers=[1, 2])
    remaining = DeckCounts(numbers={10: 1}, plus={8: 1}, x2=0)
    view = _view([me, opponent], remaining, totals=[0, 197], acting=0)

    assert LookaheadEV().decide(view) == "stay"
    assert RaceAwareEV().decide(view) == "hit"


def test_freeze_targets_flip7_threat_over_the_leader() -> None:
    # 3 seats; seat 0 drew a Freeze. Seat 1 is the total leader but nowhere
    # near Flip 7; seat 2 is one card from Flip 7 but far behind on total.
    # ADR-010's default would pick seat 1 (next active seat after seat 0);
    # a naive "always freeze the leader" rule would also pick seat 1. This
    # policy instead denies the Flip 7 threat (seat 2), since letting an
    # opponent complete Flip 7 ends the round immediately.
    acting_line = PlayerLine(numbers=[1])
    leader_line = PlayerLine(numbers=[2])
    flip7_threat_line = PlayerLine(numbers=[0, 1, 2, 3, 4, 5])
    remaining = DeckCounts(numbers={}, plus={}, x2=0)
    view = _view(
        [acting_line, leader_line, flip7_threat_line],
        remaining,
        totals=[0, 100, 0],
        acting=0,
    )
    target = RaceAwareEV().choose_target(view, freeze_card(), (0, 1, 2))
    assert target == 2


def test_freeze_targets_the_leader_when_no_flip7_threat() -> None:
    # 3 seats; seat 0 drew a Freeze. No one is close to Flip 7. Seat 2 has
    # the higher projected total (total + current partial line) than seat 1,
    # even though seat 1 is the "next active seat" ADR-010's default would
    # pick -- proving this differs from that fallback, not just coincides.
    acting_line = PlayerLine(numbers=[1])
    seat1_line = PlayerLine(numbers=[])
    seat2_line = PlayerLine(numbers=[2, 3])
    remaining = DeckCounts(numbers={}, plus={}, x2=0)
    view = _view(
        [acting_line, seat1_line, seat2_line],
        remaining,
        totals=[0, 0, 50],
        acting=0,
    )
    target = RaceAwareEV().choose_target(view, freeze_card(), (0, 1, 2))
    assert target == 2


def test_flip_three_self_targets_when_own_ev_is_good() -> None:
    # Acting seat's own line has a guaranteed-improving next card (no bust
    # risk at all) and no race threat is in play: self-targeting the forced
    # 3 draws is fine since the policy would have chosen to hit anyway.
    me = PlayerLine(numbers=[3])
    opponent = PlayerLine(numbers=[1, 2])
    remaining = DeckCounts(numbers={}, plus={2: 1}, x2=0)
    view = _view([me, opponent], remaining, totals=[0, 0], acting=0)
    target = RaceAwareEV().choose_target(view, flip_three_card(), (0, 1))
    assert target == 0


def test_flip_three_hands_off_to_leader_when_own_ev_is_bad() -> None:
    # Acting seat's own line is very likely to bust on the next card (high
    # bust risk, current score already decent): forcing 3 no-stay draws on
    # itself would be reckless, so it hands the Flip Three to the other
    # active seat instead.
    me = PlayerLine(numbers=[5, 9, 3])
    opponent = PlayerLine(numbers=[1])
    remaining = DeckCounts(numbers={5: 3, 9: 2}, plus={}, x2=0)
    view = _view([me, opponent], remaining, totals=[0, 0], acting=0)
    target = RaceAwareEV().choose_target(view, flip_three_card(), (0, 1))
    assert target == 1
