from __future__ import annotations

from flip7.engine import Policy, TableView
from flip7.probability import lookahead_ev, one_step_ev, p_bust


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


def named_policies() -> dict[str, Policy]:
    return {
        "stay_after_deal": StayAfterDeal(),
        "chase_flip7": ChaseFlip7(),
        "bust_tau_0.25": BustThreshold(0.25),
        "bust_tau_0.40": BustThreshold(0.40),
        "one_step_ev": OneStepEV(),
        "lookahead_ev": LookaheadEV(),
    }
