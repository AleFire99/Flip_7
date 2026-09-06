from __future__ import annotations

from collections.abc import Mapping

from flip7.basic_strategy import Cell, p_bust_bucket_label, plus_bucket_label
from flip7.cards import Card, CardKind
from flip7.engine import Policy, TableView
from flip7.probability import lookahead_ev, one_step_ev, p_bust
from flip7.scoring import TARGET_SCORE


class StayAfterDeal:
    name = "stay_after_deal"

    def decide(self, view: TableView) -> str:
        return "stay"


class ChaseFlip7:
    name = "chase_flip7"

    def decide(self, view: TableView) -> str:
        return "hit"


class BustThreshold:
    def __init__(self, tau: float) -> None:
        self.tau = tau
        self.name = f"bust_tau_{tau:.2f}"

    def decide(self, view: TableView) -> str:
        line = view.lines[view.acting]
        remaining = view.remaining
        if p_bust(line.numbers, remaining) >= self.tau:
            return "stay"
        return "hit"


class OneStepEV:
    name = "one_step_ev"

    def decide(self, view: TableView) -> str:
        line = view.lines[view.acting]
        stay = line.current_score()
        hit_ev = one_step_ev(
            line.numbers,
            line.plus,
            line.has_x2,
            view.remaining,
            busted=line.busted,
        )
        return "hit" if hit_ev > stay else "stay"


class LookaheadEV:
    """Option B policy: hits iff the recursive DP EV of hitting beats staying.

    Unlike :class:`OneStepEV` (myopic: values exactly one more card then
    banks), this uses :func:`flip7.probability.lookahead_ev`, which recurses
    through the optimal hit/stay choice at every future state. It is therefore
    never worse, and sometimes strictly better, than ``OneStepEV`` at valuing
    "hit again if the next card is safe" chains (ADR-008/ADR-009).
    """

    name = "lookahead_ev"

    def decide(self, view: TableView) -> str:
        line = view.lines[view.acting]
        stay = line.current_score()
        hit_ev = lookahead_ev(
            line.numbers,
            line.plus,
            line.has_x2,
            view.remaining,
            busted=line.busted,
        )
        return "hit" if hit_ev > stay else "stay"


class RaceAwareEV:
    """Option C policy (ADR-012): opponent- and race-aware hit/stay, plus
    strategic Freeze/Flip Three targeting.

    ``LookaheadEV`` (option B) is provably optimal for *one line in
    isolation* but has zero awareness of ``TableView.lines``/``totals`` --
    it hits/stays identically whether an opponent is one card from Flip 7 or
    one point from 200, or nowhere close. This policy layers a race-context
    adjustment on top of the same ``lookahead_ev`` DP:

    - It only ever adjusts the decision when a *threat* is present: an
      active opponent holds 6 unique numbers (one successful hit from
      ending the round via Flip 7) or an opponent's current total already
      meets or exceeds ``TARGET_SCORE`` (they are positioned to win the
      race outright once the round ends). Absent either signal, it behaves
      exactly like ``LookaheadEV`` -- there is no urgency to weigh yet.
    - When threatened and *not* leading (this seat's total-if-it-stays-now
      is behind the best opponent's total-if-their-round-ended-now), it
      adds a "catch-up" bonus to the hit EV, proportional to how far behind
      it is (capped, since an enormous deficit shouldn't force absurdly
      reckless hitting): the round might end abruptly, so it is worth
      accepting a slightly worse EV hit now rather than banking a total
      that is already losing.
    - When threatened and leading, it *subtracts* a fixed margin from the
      hit EV: with the round liable to end at any moment (an opponent's
      Flip 7) or already lost if it doesn't (an opponent past 200), banking
      the current lead is worth more than a marginal EV edge from hitting
      again.

    These constants are a documented, hand-picked heuristic (this is open
    research territory per ADR-009/ADR-003), not a fitted or provably
    optimal model of opponents.
    """

    name = "race_aware_ev"

    #: Points of "opponent lead" beyond which extra deficit stops adding to
    #: the catch-up bonus (an enormous deficit shouldn't imply near-suicidal
    #: hitting -- a capped, diminishing incentive is more defensible).
    DEFICIT_CAP = 40.0
    #: Fraction of the (capped) deficit added to hit EV when behind & threatened.
    CATCH_UP_RATE = 0.25
    #: Flat hit-EV penalty applied when leading & threatened, favoring banking
    #: the current lead over a marginal further gain.
    LEAD_PROTECT_MARGIN = 6.0

    def decide(self, view: TableView) -> str:
        line = view.lines[view.acting]
        stay_value = float(line.current_score())
        hit_ev = lookahead_ev(
            line.numbers,
            line.plus,
            line.has_x2,
            view.remaining,
            busted=line.busted,
        )
        adjusted = self._race_adjusted_hit_ev(view, hit_ev, stay_value)
        return "hit" if adjusted > stay_value else "stay"

    def _race_adjusted_hit_ev(self, view: TableView, hit_ev: float, stay_value: float) -> float:
        acting = view.acting
        opponents = [i for i in range(len(view.lines)) if i != acting]
        if not opponents:
            return hit_ev

        opponent_projected = [view.totals[i] + view.lines[i].current_score() for i in opponents]
        opponent_best = max(opponent_projected)
        my_projected_if_stay = view.totals[acting] + stay_value
        leading = my_projected_if_stay >= opponent_best

        flip7_threat = any(
            view.lines[i].active and len(view.lines[i].numbers) == 6 for i in opponents
        )
        endgame_threat = any(p >= TARGET_SCORE for p in opponent_projected)
        if not (flip7_threat or endgame_threat):
            return hit_ev

        if leading:
            return hit_ev - self.LEAD_PROTECT_MARGIN
        deficit = max(0.0, opponent_best - my_projected_if_stay)
        bonus = min(deficit, self.DEFICIT_CAP) * self.CATCH_UP_RATE
        return hit_ev + bonus

    def choose_target(self, view: TableView, card: Card, candidates: tuple[int, ...]) -> int:
        """ADR-012 targeting: deny Flip 7 / protect against the leader.

        ``candidates`` always includes the acting seat itself (ADR-010); this
        implementation only ever self-targets a Flip Three (never a Freeze --
        freezing yourself mid-hit is never useful since ``decide`` already
        had the chance to choose "stay" first).
        """
        acting = view.acting
        others = [i for i in candidates if i != acting]
        if card.kind is CardKind.FLIP_THREE:
            return self._choose_flip_three_target(view, acting, others)
        return self._choose_freeze_target(view, others, acting)

    def _choose_freeze_target(self, view: TableView, others: list[int], acting: int) -> int:
        if not others:
            return acting
        flip7_threats = [
            i for i in others if view.lines[i].active and len(view.lines[i].numbers) == 6
        ]
        if flip7_threats:
            # Deny whichever near-Flip-7 line has banked the most so far --
            # the most valuable one to stop before it reaches the +15 bonus
            # and ends the round.
            return max(flip7_threats, key=lambda i: view.lines[i].current_score())
        # Nobody is one card from Flip 7: freeze the current leader (by
        # projected total) to stop them growing their lead any further,
        # rather than always the merely-next seat (ADR-010's default).
        return max(others, key=lambda i: view.totals[i] + view.lines[i].current_score())

    def _choose_flip_three_target(self, view: TableView, acting: int, others: list[int]) -> int:
        if not others:
            return acting
        line = view.lines[acting]
        stay_value = float(line.current_score())
        hit_ev = lookahead_ev(
            line.numbers,
            line.plus,
            line.has_x2,
            view.remaining,
            busted=line.busted,
        )
        adjusted = self._race_adjusted_hit_ev(view, hit_ev, stay_value)
        if adjusted > stay_value:
            # My own line is currently worth hitting anyway: take the 3
            # forced draws myself rather than risk handing a good line's
            # worth of EV to an opponent.
            return acting
        # My line isn't worth hitting right now: hand the forced, no-stay
        # draws to the current leader (by projected total) instead, raising
        # their bust risk rather than mine.
        return max(others, key=lambda i: view.totals[i] + view.lines[i].current_score())


#: The shipped basic-strategy chart (ADR-013, re-keyed by ADR-016): the
#: literal output of `flip7.basic_strategy.generate_basic_strategy_table(
#: seed=1, samples_per_cell=60).chart()`, baked in here so `BasicStrategy` is
#: a cheap dict lookup rather than a fresh multi-minute `lookahead_ev`
#: distillation on every import/decision -- exactly like a printed Blackjack
#: strategy card is computed once and then just read. Keyed on a coarse
#: P(bust) bucket and whether the hand is one card from Flip 7, rather than
#: raw card count (ADR-016) -- see docs/DECISIONS.md for why raw count alone
#: hid a large, provable effect. Regenerate with
#: `flip7 basic-strategy --seed 1 --out reports` (see
#: reports/basic_strategy.txt for the plain-language version and the
#: measured win-rate/EV gap versus `lookahead_ev`).
BASIC_STRATEGY_CHART: dict[Cell, str] = {
    ("<10%", False, False, "0"): "hit",
    ("<10%", False, False, "1-5"): "hit",
    ("<10%", False, False, "6+"): "hit",
    ("<10%", False, True, "0"): "hit",
    ("<10%", False, True, "1-5"): "hit",
    ("<10%", False, True, "6+"): "hit",
    ("<10%", True, False, "0"): "stay",
    ("<10%", True, False, "1-5"): "stay",
    ("<10%", True, False, "6+"): "stay",
    ("<10%", True, True, "0"): "stay",
    ("<10%", True, True, "1-5"): "stay",
    ("<10%", True, True, "6+"): "stay",
    ("10-27%", False, False, "0"): "hit",
    ("10-27%", False, False, "1-5"): "hit",
    ("10-27%", False, False, "6+"): "hit",
    ("10-27%", False, True, "0"): "hit",
    ("10-27%", False, True, "1-5"): "hit",
    ("10-27%", False, True, "6+"): "hit",
    ("10-27%", True, False, "0"): "hit",
    ("10-27%", True, False, "1-5"): "hit",
    ("10-27%", True, False, "6+"): "stay",
    ("10-27%", True, True, "0"): "hit",
    ("10-27%", True, True, "1-5"): "stay",
    ("10-27%", True, True, "6+"): "stay",
    ("27-40%", False, False, "0"): "stay",
    ("27-40%", False, False, "1-5"): "stay",
    ("27-40%", False, False, "6+"): "stay",
    ("27-40%", False, True, "0"): "stay",
    ("27-40%", False, True, "1-5"): "stay",
    ("27-40%", False, True, "6+"): "stay",
    ("27-40%", True, False, "0"): "hit",
    ("27-40%", True, False, "1-5"): "stay",
    ("27-40%", True, False, "6+"): "stay",
    ("27-40%", True, True, "0"): "stay",
    ("27-40%", True, True, "1-5"): "stay",
    ("27-40%", True, True, "6+"): "stay",
    ("40%+", False, False, "0"): "stay",
    ("40%+", False, False, "1-5"): "stay",
    ("40%+", False, False, "6+"): "stay",
    ("40%+", False, True, "0"): "stay",
    ("40%+", False, True, "1-5"): "stay",
    ("40%+", False, True, "6+"): "stay",
    ("40%+", True, False, "0"): "stay",
    ("40%+", True, False, "1-5"): "stay",
    ("40%+", True, False, "6+"): "stay",
    ("40%+", True, True, "0"): "stay",
    ("40%+", True, True, "1-5"): "stay",
    ("40%+", True, True, "6+"): "stay",
}


class BasicStrategy:
    """Blackjack-style memorizable hit/stay chart distilled from `lookahead_ev`.

    Looks up a fixed recommendation keyed by a small cell -- a coarse P(bust)
    bucket, whether the hand is one card from Flip 7, whether `x2` is held,
    and a coarse bucket of the current `+` total (ADR-016) -- instead of
    solving the live remaining deck the way `LookaheadEV` does. Unlike the
    other axes, P(bust) is computed exactly from `view.remaining` here (this
    policy already has perfect info per ADR-002, so there's no reason to
    throw that away); a human at the table without exact deck knowledge can
    use the cheap `sum(held card values)` approximation documented in
    ADR-016 instead, which tracks the same bucket boundaries closely. The
    chart itself is generated by
    `flip7.basic_strategy.generate_basic_strategy_table`, which averages
    `lookahead_ev`'s hit/stay verdict over a representative sample of
    plausible mid-game remaining decks per cell (ADR-013); this policy is
    just a cheap lookup against that pre-computed table so its real win rate
    can be simulated like any other policy.
    """

    name = "basic_strategy"

    def __init__(self, chart: Mapping[Cell, str] | None = None) -> None:
        self._chart: dict[Cell, str] = dict(chart) if chart is not None else dict(
            BASIC_STRATEGY_CHART
        )

    def decide(self, view: TableView) -> str:
        line = view.lines[view.acting]
        pb = p_bust(line.numbers, view.remaining)
        cell: Cell = (
            p_bust_bucket_label(pb),
            line.unique_count == 6,
            line.has_x2,
            plus_bucket_label(line.plus),
        )
        return self._chart.get(cell, "stay")


def named_policies() -> dict[str, Policy]:
    return {
        "stay_after_deal": StayAfterDeal(),
        "chase_flip7": ChaseFlip7(),
        "bust_tau_0.25": BustThreshold(0.25),
        "bust_tau_0.40": BustThreshold(0.40),
        "one_step_ev": OneStepEV(),
        "lookahead_ev": LookaheadEV(),
        "race_aware_ev": RaceAwareEV(),
        "basic_strategy": BasicStrategy(),
    }
