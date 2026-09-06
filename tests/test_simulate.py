from __future__ import annotations

import random

from flip7.simulate import simulate_games
from flip7.strategy import ChaseFlip7, OneStepEV, StayAfterDeal


def test_simulate_runs_three_policies() -> None:
    report = simulate_games(
        [StayAfterDeal(), OneStepEV(), ChaseFlip7()],
        n_games=6,
        seed=0,
    )
    assert report.n_games == 6
    assert report.wins.sum() + report.unfinished == 6
    assert len(report.policy_names) == 3


def test_one_step_ev_beats_pure_stay_on_average() -> None:
    rng = random.Random(0)
    stay_scores = []
    ev_scores = []
    from flip7.engine import play_round

    for _ in range(20):
        stay = play_round([StayAfterDeal(), StayAfterDeal(), StayAfterDeal()], rng)
        stay_scores.append(stay.scores[0])
        ev = play_round([OneStepEV(), StayAfterDeal(), StayAfterDeal()], rng)
        ev_scores.append(ev.scores[0])
    assert sum(ev_scores) >= sum(stay_scores) - 50
