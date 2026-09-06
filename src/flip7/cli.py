from __future__ import annotations

import argparse
import random
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from flip7.cards import full_deck
from flip7.engine import Policy, play_round
from flip7.probability import (
    lookahead_ev,
    one_step_ev,
    p_bust,
    p_flip7_this_hit,
    p_modifier,
    subtract_visible,
)
from flip7.scoring import TARGET_SCORE
from flip7.simulate import SimulationReport, compare_to_baseline, simulate_games
from flip7.strategy import BustThreshold, ChaseFlip7, OneStepEV, StayAfterDeal, named_policies

DEFAULT_COMPARE_BASELINES = ("stay_after_deal", "chase_flip7", "one_step_ev")


def _write_summary(path: Path, report: SimulationReport) -> None:
    lines = [
        f"Flip 7 Phase 1 simulation ({report.n_games} games, seed={report.seed})",
        f"Mean rounds to finish (or cap): {report.mean_rounds:.2f}",
        f"Unfinished (hit round cap): {report.unfinished}",
        "",
        f"{'policy':<20} {'wins':>8} {'win%':>8} {'mean tot':>10} "
        f"{'bust/g':>8} {'F7/g':>8} {'avg rnd':>8}",
    ]
    for i, name in enumerate(report.policy_names):
        win_pct = 100.0 * report.wins[i] / max(report.n_games, 1)
        lines.append(
            f"{name:<20} {int(report.wins[i]):>8} {win_pct:>7.1f}% "
            f"{report.mean_totals[i]:>10.1f} {report.mean_busts[i]:>8.2f} "
            f"{report.mean_flip7s[i]:>8.2f} {report.mean_round_score[i]:>8.1f}"
        )
    lines.extend(
        [
            "",
            "Policies: stay_after_deal banks the opening card; chase_flip7 always hits;",
            "bust_tau stays when P(bust) is at least the threshold; one_step_ev hits",
            "iff expected score after one more card (then stay) exceeds the current score",
            "(analysis option A, myopic). lookahead_ev hits iff the recursive DP EV of",
            "hitting -- which itself picks max(stay, hit) at every future state -- exceeds",
            "the current score (analysis option B; see 'flip7 compare' for head-to-head",
            "results against the option A policies).",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _plot_win_rates(path: Path, report: SimulationReport) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = np.arange(len(report.policy_names))
    rates = 100.0 * report.wins / max(report.n_games, 1)
    ax.bar(x, rates)
    ax.set_xticks(x, report.policy_names, rotation=20, ha="right")
    ax.set_ylabel("Win rate (%)")
    ax.set_title(f"Race to 200 ({report.n_games} games)")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _plot_round_stats(path: Path, report: SimulationReport) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(9, 4))
    x = np.arange(len(report.policy_names))
    axes[0].bar(x, report.mean_round_score)
    axes[0].set_xticks(x, report.policy_names, rotation=20, ha="right")
    axes[0].set_ylabel("Mean round score")
    axes[1].bar(x, report.mean_busts)
    axes[1].set_xticks(x, report.policy_names, rotation=20, ha="right")
    axes[1].set_ylabel("Mean busts per game")
    fig.suptitle("Round outcomes by seat policy")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _resolve_policies(names: list[str]) -> list[Policy]:
    registry = named_policies()
    unknown = [name for name in names if name not in registry]
    if unknown:
        msg = f"unknown policy names: {unknown} (known: {sorted(registry)})"
        raise SystemExit(msg)
    return [registry[name] for name in names]


def cmd_analyze(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.policies:
        names = [name.strip() for name in args.policies.split(",") if name.strip()]
        policies = _resolve_policies(names)
    elif args.include_threshold:
        policies = [StayAfterDeal(), BustThreshold(0.25), OneStepEV()]
    else:
        policies = [StayAfterDeal(), ChaseFlip7(), OneStepEV()]
    report = simulate_games(
        policies,
        n_games=args.games,
        seed=args.seed,
        target=args.target,
        max_rounds=args.max_rounds,
    )
    _write_summary(out / "summary.txt", report)
    _plot_win_rates(out / "win_rates.png", report)
    _plot_round_stats(out / "round_stats.png", report)
    print((out / "summary.txt").read_text(encoding="utf-8"))
    return 0


def _write_compare_table(
    path: Path,
    baselines: list[str],
    results: dict[str, list[tuple[str, SimulationReport]]],
    n_games: int,
    seed: int,
) -> None:
    lines = [
        f"Flip 7 policy comparison ({n_games} games/matchup, seed={seed})",
        "Each row is a 2-seat [challenger, baseline] game; win% is the challenger's.",
        "",
    ]
    for baseline_name in baselines:
        lines.append(f"=== challenger vs {baseline_name} ===")
        lines.append(
            f"{'policy':<20} {'win%':>8} {'mean tot':>10} {'bust/g':>8} {'F7/g':>8}"
        )
        for name, report in results[baseline_name]:
            win_pct = 100.0 * report.wins[0] / max(report.n_games, 1)
            lines.append(
                f"{name:<20} {win_pct:>7.1f}% {report.mean_totals[0]:>10.1f} "
                f"{report.mean_busts[0]:>8.2f} {report.mean_flip7s[0]:>8.2f}"
            )
        lines.append("")
    lines.append(
        "lookahead_ev is the recursive DP (option B) policy; it is the slowest"
    )
    lines.append(
        "entry above since it solves an optimal hit/stay policy from scratch on"
    )
    lines.append(
        "every decision. Narrow --policies/--baselines or lower --games to iterate faster."
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_compare(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    baselines = [name.strip() for name in args.baselines.split(",") if name.strip()]
    policy_names = (
        [name.strip() for name in args.policies.split(",") if name.strip()]
        if args.policies
        else None
    )
    results: dict[str, list[tuple[str, SimulationReport]]] = {}
    for baseline_name in baselines:
        results[baseline_name] = compare_to_baseline(
            baseline_name,
            args.games,
            args.seed,
            policy_names,
            target=args.target,
            max_rounds=args.max_rounds,
        )
    _write_compare_table(out / "compare.txt", baselines, results, args.games, args.seed)
    print((out / "compare.txt").read_text(encoding="utf-8"))
    return 0


def cmd_ev_table(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed)
    deck = full_deck()
    rng.shuffle(deck)
    result = play_round([StayAfterDeal(), StayAfterDeal(), StayAfterDeal()], rng, deck=deck)
    visible = [c for line in result.lines for c in line.cards]
    remaining = subtract_visible(visible)
    print("After initial deal (all stayed):")
    for i, line in enumerate(result.lines):
        stay = line.current_score()
        ev = one_step_ev(line.numbers, line.plus, line.has_x2, remaining)
        dp_ev = lookahead_ev(line.numbers, line.plus, line.has_x2, remaining)
        print(
            f"  seat {i}: cards={[c.label() for c in line.cards]} "
            f"score={stay} P(bust)={p_bust(line.numbers, remaining):.3f} "
            f"P(mod)={p_modifier(remaining):.3f} "
            f"P(F7 hit)={p_flip7_this_hit(line.numbers, remaining):.3f} "
            f"one-step EV={ev:.2f} -> {'HIT' if ev > stay else 'STAY'} | "
            f"lookahead EV={dp_ev:.2f} -> {'HIT' if dp_ev > stay else 'STAY'}"
        )
    return 0


def cmd_policies(_args: argparse.Namespace) -> int:
    print("\n".join(named_policies()))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flip7", description="Flip 7 Phase 1 analysis")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="Simulate 3-player race to 200")
    analyze.add_argument("--games", type=int, default=2000)
    analyze.add_argument("--seed", type=int, default=1)
    analyze.add_argument("--out", type=str, default="reports")
    analyze.add_argument(
        "--include-threshold",
        action="store_true",
        help="Swap chase_flip7 for bust_tau_0.25 in the three seats (ignored if --policies is set)",
    )
    analyze.add_argument(
        "--policies",
        type=str,
        default=None,
        help=(
            "Comma-separated policy names (see 'flip7 policies') for a custom "
            "mixed seating, any length; overrides --include-threshold"
        ),
    )
    analyze.add_argument(
        "--target",
        type=int,
        default=TARGET_SCORE,
        help="Race-to score (lower it for quick smoke runs with slow policies)",
    )
    analyze.add_argument("--max-rounds", type=int, default=400, dest="max_rounds")
    analyze.set_defaults(func=cmd_analyze)

    ev = sub.add_parser("ev-table", help="Print one-step and lookahead EV after a sample deal")
    ev.add_argument("--seed", type=int, default=1)
    ev.set_defaults(func=cmd_ev_table)

    policies = sub.add_parser("policies", help="List built-in policies")
    policies.set_defaults(func=cmd_policies)

    compare = sub.add_parser(
        "compare",
        help=(
            "Compare policies 1v1 against fixed baselines "
            "(default: all vs stay_after_deal/chase_flip7/one_step_ev)"
        ),
    )
    compare.add_argument("--games", type=int, default=100)
    compare.add_argument("--seed", type=int, default=1)
    compare.add_argument("--out", type=str, default="reports")
    compare.add_argument(
        "--baselines",
        type=str,
        default=",".join(DEFAULT_COMPARE_BASELINES),
        help="Comma-separated baseline policy names, one 2-seat table per baseline",
    )
    compare.add_argument(
        "--policies",
        type=str,
        default=None,
        help="Comma-separated challenger policy names (default: every registered policy)",
    )
    compare.add_argument(
        "--target",
        type=int,
        default=TARGET_SCORE,
        help="Race-to score (lower it for quick smoke runs with slow policies like lookahead_ev)",
    )
    compare.add_argument("--max-rounds", type=int, default=400, dest="max_rounds")
    compare.set_defaults(func=cmd_compare)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))
