from __future__ import annotations

import argparse
import random
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from flip7.cards import full_deck
from flip7.engine import Policy, play_round
from flip7.probability import (
    one_step_ev,
    p_bust,
    p_flip7_this_hit,
    p_modifier,
    subtract_visible,
)
from flip7.simulate import SimulationReport, simulate_games
from flip7.strategy import BustThreshold, ChaseFlip7, OneStepEV, StayAfterDeal, named_policies


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
            "iff expected score after one more card (then stay) exceeds the current score.",
            "This is analysis option A (myopic EV). Option B (recursive solo EV) is not",
            "implemented.",
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


def cmd_analyze(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    policies: list[Policy] = [
        StayAfterDeal(),
        ChaseFlip7(),
        OneStepEV(),
    ]
    if args.include_threshold:
        policies = [
            StayAfterDeal(),
            BustThreshold(0.25),
            OneStepEV(),
        ]
    report = simulate_games(policies, n_games=args.games, seed=args.seed)
    _write_summary(out / "summary.txt", report)
    _plot_win_rates(out / "win_rates.png", report)
    _plot_round_stats(out / "round_stats.png", report)
    print((out / "summary.txt").read_text(encoding="utf-8"))
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
        print(
            f"  seat {i}: cards={[c.label() for c in line.cards]} "
            f"score={stay} P(bust)={p_bust(line.numbers, remaining):.3f} "
            f"P(mod)={p_modifier(remaining):.3f} "
            f"P(F7 hit)={p_flip7_this_hit(line.numbers, remaining):.3f} "
            f"one-step EV={ev:.2f} -> {'HIT' if ev > stay else 'STAY'}"
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
        help="Swap chase_flip7 for bust_tau_0.25 in the three seats",
    )
    analyze.set_defaults(func=cmd_analyze)

    ev = sub.add_parser("ev-table", help="Print one-step EV after a sample deal")
    ev.add_argument("--seed", type=int, default=1)
    ev.set_defaults(func=cmd_ev_table)

    policies = sub.add_parser("policies", help="List built-in policies")
    policies.set_defaults(func=cmd_policies)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))
