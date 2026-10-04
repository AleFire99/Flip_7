from __future__ import annotations

import functools
import math
import random
from collections.abc import Callable
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


#: Two-sided 95% normal quantile.
Z95 = 1.96


@dataclass
class PairedComparison:
    """Seat-swapped, common-random-number comparison of one challenger vs a baseline.

    Each pair plays the same seed twice: ``[challenger, baseline]`` then
    ``[baseline, challenger]``. Both games shuffle the same deck from the same
    RNG state, so the only thing that differs is who sits where (and, since the
    dealer is always seat 0, who deals/acts first). Games inside a pair are
    correlated, so every interval below is computed over *pairs*, not games.
    """

    challenger: str
    baseline: str
    n_pairs: int
    seed: int
    challenger_wins: int
    baseline_wins: int
    unfinished: int
    win_rate: float
    win_rate_ci: tuple[float, float]
    paired_diff: float
    paired_diff_ci: tuple[float, float]
    first_seat_win_rate: float
    mean_total_challenger: float
    mean_total_baseline: float

    @property
    def n_games(self) -> int:
        return 2 * self.n_pairs

    @property
    def diff_significant(self) -> bool:
        lo, hi = self.paired_diff_ci
        return lo > 0 or hi < 0


def _mean_ci(values: np.ndarray) -> tuple[float, tuple[float, float]]:
    n = len(values)
    mean = float(values.mean()) if n else 0.0
    if n < 2:
        return mean, (mean, mean)
    half = Z95 * float(values.std(ddof=1)) / math.sqrt(n)
    return mean, (mean - half, mean + half)


def compare_paired(
    challenger: Policy,
    baseline: Policy,
    n_pairs: int,
    seed: int,
    *,
    target: int = TARGET_SCORE,
    max_rounds: int = 400,
    progress: Callable[[int, int], None] | None = None,
) -> PairedComparison:
    """Play ``n_pairs`` seed-paired, seat-swapped games (``2 * n_pairs`` games)."""
    master = random.Random(seed)
    chal_share = np.zeros(n_pairs)  # challenger win rate within each pair (0, .5, 1)
    diff = np.zeros(n_pairs)  # (challenger wins - baseline wins) / 2 within each pair
    chal_wins = base_wins = unfinished = 0
    first_seat_wins = 0
    tot_c = tot_b = 0.0
    for i in range(n_pairs):
        pair_seed = master.randrange(2**63)
        pair_c = pair_b = 0
        for chal_seat in (0, 1):
            policies = [challenger, baseline] if chal_seat == 0 else [baseline, challenger]
            result = play_game(
                policies, random.Random(pair_seed), target=target, max_rounds=max_rounds
            )
            tot_c += result.totals[chal_seat]
            tot_b += result.totals[1 - chal_seat]
            if result.winner is None:
                unfinished += 1
                continue
            if result.winner == 0:
                first_seat_wins += 1
            if result.winner == chal_seat:
                pair_c += 1
            else:
                pair_b += 1
        chal_wins += pair_c
        base_wins += pair_b
        chal_share[i] = pair_c / 2
        diff[i] = (pair_c - pair_b) / 2
        if progress is not None:
            progress(i + 1, n_pairs)
    win_rate, win_ci = _mean_ci(chal_share)
    paired_diff, diff_ci = _mean_ci(diff)
    n_games = max(2 * n_pairs, 1)
    return PairedComparison(
        challenger=challenger.name,
        baseline=baseline.name,
        n_pairs=n_pairs,
        seed=seed,
        challenger_wins=chal_wins,
        baseline_wins=base_wins,
        unfinished=unfinished,
        win_rate=win_rate,
        win_rate_ci=win_ci,
        paired_diff=paired_diff,
        paired_diff_ci=diff_ci,
        first_seat_win_rate=first_seat_wins / n_games,
        mean_total_challenger=tot_c / n_games,
        mean_total_baseline=tot_b / n_games,
    )


def compare_paired_to_baseline(
    baseline_name: str,
    n_games: int,
    seed: int,
    policy_names: list[str] | None = None,
    *,
    target: int = TARGET_SCORE,
    max_rounds: int = 400,
    progress: Callable[[str, int, int], None] | None = None,
) -> list[tuple[str, PairedComparison]]:
    """Paired, seat-swapped counterpart of :func:`compare_to_baseline`.

    ``n_games`` is the total number of games per matchup; it is rounded up to
    whole pairs (two games each).
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

    n_pairs = max(1, math.ceil(n_games / 2))
    results: list[tuple[str, PairedComparison]] = []
    for name in names:
        fresh = named_policies()
        results.append(
            (
                name,
                compare_paired(
                    fresh[name],
                    fresh[baseline_name],
                    n_pairs,
                    seed,
                    target=target,
                    max_rounds=max_rounds,
                    progress=functools.partial(progress, name) if progress else None,
                ),
            )
        )
    return results
