from __future__ import annotations

import random
from dataclasses import dataclass

import numpy as np

from flip7.engine import Policy, play_game


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
        result = play_game(policies, rng)
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
