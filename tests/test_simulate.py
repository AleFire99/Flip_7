from __future__ import annotations

import random

import pytest

from flip7.simulate import compare_to_baseline, simulate_games
from flip7.strategy import ChaseFlip7, OneStepEV, StayAfterDeal, named_policies


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


def test_compare_to_baseline_covers_every_registered_policy() -> None:
    # lookahead_ev is slow; race to a trivial target so this test stays fast.
    results = compare_to_baseline("stay_after_deal", n_games=2, seed=0, target=1, max_rounds=2)
    names = [name for name, _ in results]
    assert names == list(named_policies())
    for name, report in results:
        assert report.policy_names == [name, "stay_after_deal"]
        assert report.n_games == 2


def test_compare_to_baseline_can_restrict_challengers() -> None:
    results = compare_to_baseline(
        "one_step_ev",
        n_games=2,
        seed=0,
        policy_names=["lookahead_ev", "chase_flip7"],
        target=1,
        max_rounds=2,
    )
    assert [name for name, _ in results] == ["lookahead_ev", "chase_flip7"]


def test_compare_to_baseline_rejects_unknown_names() -> None:
    with pytest.raises(ValueError, match="unknown baseline"):
        compare_to_baseline("not_a_policy", n_games=2, seed=0)
    with pytest.raises(ValueError, match="unknown policy"):
        compare_to_baseline("stay_after_deal", n_games=2, seed=0, policy_names=["nope"])
