from __future__ import annotations

import random
from dataclasses import dataclass

import numpy as np

from flip7.engine import Policy, play_game
from flip7.scoring import TARGET_SCORE


@dataclass
class SimulationReport:
    policy_names: list[str]
    n_games: int
    seed: int
    wins: np.ndarray
    unfinished: int
    mean_rounds: float
    mean_totals: np.ndarray
    mean_busts: np.ndarray
    mean_flip7s: np.ndarray
    mean_round_score: np.ndarray


def simulate_games(
    policies: list[Policy],
    n_games: int,
    seed: int,
    *,
    target: int = TARGET_SCORE,
    max_rounds: int = 400,
) -> SimulationReport:
    rng = random.Random(seed)
    n = len(policies)
    wins = np.zeros(n, dtype=np.int64)
    unfinished = 0
    rounds: list[int] = []
    totals = np.zeros((n_games, n), dtype=np.float64)
    busts = np.zeros((n_games, n), dtype=np.float64)
    flip7s = np.zeros((n_games, n), dtype=np.float64)
    round_score_sum = np.zeros(n, dtype=np.float64)
    round_score_n = np.zeros(n, dtype=np.float64)

    for g in range(n_games):
        result = play_game(policies, rng, target=target, max_rounds=max_rounds)
        if result.winner is None:
            unfinished += 1
        else:
            wins[result.winner] += 1
        rounds.append(result.rounds)
        totals[g] = result.totals
        busts[g] = result.busts
        flip7s[g] = result.flip7s
        for scores in result.round_scores:
            round_score_sum += scores
            round_score_n += 1

    names = [p.name for p in policies]
    mean_round = np.divide(
        round_score_sum,
        np.maximum(round_score_n, 1),
    )
    return SimulationReport(
        policy_names=names,
        n_games=n_games,
        seed=seed,
        wins=wins,
        unfinished=unfinished,
        mean_rounds=float(np.mean(rounds)) if rounds else 0.0,
        mean_totals=totals.mean(axis=0),
        mean_busts=busts.mean(axis=0),
        mean_flip7s=flip7s.mean(axis=0),
        mean_round_score=mean_round,
    )


def compare_to_baseline(
    baseline_name: str,
    n_games: int,
    seed: int,
    policy_names: list[str] | None = None,
    *,
    target: int = TARGET_SCORE,
    max_rounds: int = 400,
) -> list[tuple[str, SimulationReport]]:
    """Run every registered policy (or a chosen subset) 1v1 against one baseline.

    Each matchup is an independent two-seat ``[challenger, baseline]`` game, so
    win rates are directly comparable across challengers without needing an
    exhaustive round robin across every pair of registered policies. Fresh
    policy instances are built per matchup so no state leaks between seats.
    """
    from flip7.strategy import named_policies

    registry = named_policies()
    if baseline_name not in registry:
        msg = f"unknown baseline policy: {baseline_name!r} (known: {sorted(registry)})"
        raise ValueError(msg)
    names = policy_names if policy_names is not None else list(registry)
    unknown = [name for name in names if name not in registry]
    if unknown:
        msg = f"unknown policy names: {unknown} (known: {sorted(registry)})"
        raise ValueError(msg)

    results: list[tuple[str, SimulationReport]] = []
    for name in names:
        fresh = named_policies()
        challenger = fresh[name]
        baseline = fresh[baseline_name]
        report = simulate_games(
            [challenger, baseline],
            n_games=n_games,
            seed=seed,
            target=target,
            max_rounds=max_rounds,
        )
        results.append((name, report))
    return results
