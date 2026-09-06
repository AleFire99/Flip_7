from __future__ import annotations

import argparse
import random
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap

from flip7.basic_strategy import (
    PLUS_BUCKETS,
    UNIQUE_COUNTS,
    BasicStrategyTable,
    generate_basic_strategy_table,
)
from flip7.cards import full_deck
from flip7.engine import Policy, TraceEvent, play_game, play_round
from flip7.probability import (
    DeckCounts,
    full_counts,
    lookahead_ev,
    one_step_ev,
    p_bust,
    p_flip7_this_hit,
    p_modifier,
    subtract_visible,
)
from flip7.scoring import TARGET_SCORE, score_line
from flip7.simulate import SimulationReport, compare_to_baseline, simulate_games
from flip7.strategy import (
    BasicStrategy,
    BustThreshold,
    ChaseFlip7,
    OneStepEV,
    StayAfterDeal,
    named_policies,
)

DEFAULT_COMPARE_BASELINES = ("stay_after_deal", "chase_flip7", "one_step_ev")
DEFAULT_BASIC_STRATEGY_BASELINES = (
    "lookahead_ev",
    "stay_after_deal",
    "chase_flip7",
    "one_step_ev",
)


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


def _format_trace_event(event: TraceEvent) -> str:
    if event.kind == "round_start":
        return f"=== Round {event.round_no} (dealer: seat {event.dealer}) ==="
    if event.kind == "round_end":
        return (
            f"  Round {event.round_no} end: scores={event.scores} "
            f"totals={event.totals} flip7={event.flip7_seat}"
        )
    verb = "deals" if event.kind == "deal" else "hits"
    if event.card is None:
        return f"  seat {event.seat} stays"
    if event.card == "Freeze":
        return (
            f"  seat {event.seat} {verb}: Freeze -> targets seat {event.target} "
            f"({event.target_via}); seat {event.target} stays"
        )
    if event.card == "Flip Three":
        return (
            f"  seat {event.seat} {verb}: Flip Three -> targets seat {event.target} "
            f"({event.target_via})"
        )
    if event.card == "Second Chance":
        if event.target is not None:
            return f"  seat {event.seat} {verb}: Second Chance -> passed to seat {event.target}"
        return f"  seat {event.seat} {verb}: Second Chance (held)"
    return f"  seat {event.seat} {verb}: {event.card} ({event.outcome})"


def _format_trace(events: list[TraceEvent]) -> str:
    return "\n".join(_format_trace_event(event) for event in events) + "\n"


def cmd_replay(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.policies:
        names = [name.strip() for name in args.policies.split(",") if name.strip()]
        policies = _resolve_policies(names)
    else:
        policies = [StayAfterDeal(), StayAfterDeal(), StayAfterDeal()]
    rng = random.Random(args.seed)
    trace: list[TraceEvent] = []
    play_game(
        policies,
        rng,
        target=args.target,
        max_rounds=args.max_rounds,
        use_action_cards=(args.deck == 94),
        trace=trace,
    )
    text = _format_trace(trace)
    (out / "replay.txt").write_text(text, encoding="utf-8")
    print(text)
    return 0


#: One representative plus-total per `flip7.basic_strategy.PLUS_BUCKETS` bucket
#: ("0", "1-5", "6+"): 0, 5, 10.
_PLUS_REPRESENTATIVES: tuple[tuple[str, int], ...] = (("0", 0), ("1-5", 5), ("6+", 10))


#: Two fixed representative held-number sets per `unique_count`, deliberately
#: not sampled (identity-vs-count is concern 1, out of scope for this
#: concern-2-only investigation -- see ADR-013's addendum). "low" turned out
#: to be degenerate on its own: {0, 1, 2, ...} has almost no duplication risk
#: (values 0/1 have only 1 copy each in the deck), so every cell recommends
#: "hit" regardless of modifiers -- nowhere near the actual hit/stay
#: boundary, so it cannot show whether a modifier ever flips a verdict.
#: "high" ({12, 11, 10, ...}, the deck's most-duplicated values) sits much
#: closer to that boundary, so both are reported side by side.
_HELD_REPRESENTATIVES: tuple[tuple[str, object], ...] = (
    ("low", lambda k: list(range(k))),
    ("high", lambda k: list(range(12, 12 - k, -1))),
)


def _remaining_after(numbers: list[int]) -> DeckCounts:
    remaining = full_counts()
    for value in numbers:
        remaining.numbers[value] -= 1
    return remaining


def cmd_modifier_effect(args: argparse.Namespace) -> int:
    """Issue #13 concern 2: does a held x2/plus modifier ever change the
    hit/stay verdict, via an exact, deterministic paired delta against
    `lookahead_ev` (no Monte Carlo sampling, unlike `flip7.basic_strategy`'s
    chart) -- see ADR-013's addendum in docs/DECISIONS.md.
    """
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    lines = [
        "Flip 7 modifier-effect investigation (issue #13, concern 2)",
        "",
        "Deterministic paired delta against exact lookahead_ev: for each unique_count,",
        "held numbers are fixed (see representatives below) and the remaining deck is",
        "the full deck minus those held numbers -- no Monte Carlo sampling, no",
        "depletion noise, unlike flip7.basic_strategy's chart. has_x2 and plus_total",
        "(one representative value per PLUS_BUCKETS bucket) are toggled to see",
        "whether the hit/stay verdict ever flips.",
        "",
        "Note: lookahead_ev(numbers, plus, has_x2, remaining) returns",
        "max(stay_value, hit_value) at the root state, not hit_value alone -- so",
        "'hit_ev' below equals 'stay' exactly whenever hitting is no better than",
        "staying (an exact DP tie), not just when it is worse. -> in this report",
        "always resolves an exact tie as 'stay' (strict >), matching",
        "flip7.basic_strategy.evaluate_cell's own convention.",
        "",
    ]
    any_flip = False
    for rep_name, held_fn in _HELD_REPRESENTATIVES:
        lines.append(f"=== held representative: {rep_name} ===")
        for unique_count in range(7):
            numbers = held_fn(unique_count)  # type: ignore[operator]
            remaining = _remaining_after(numbers)
            cells: dict[tuple[bool, int], tuple[float, float, str]] = {}
            lines.append(f"unique_count={unique_count} (held={numbers}):")
            for has_x2 in (False, True):
                for label, plus_total in _PLUS_REPRESENTATIVES:
                    hit_ev = lookahead_ev(numbers, plus_total, has_x2, remaining)
                    stay_value = float(score_line(numbers, plus_total, has_x2, False))
                    decision = "hit" if hit_ev > stay_value else "stay"
                    cells[(has_x2, plus_total)] = (hit_ev, stay_value, decision)
                    lines.append(
                        f"  x2={has_x2!s:<5} plus={label:<4} hit_ev={hit_ev:8.2f} "
                        f"stay={stay_value:8.2f} -> {decision}"
                    )
            x2_flip_at = [
                label
                for label, plus_total in _PLUS_REPRESENTATIVES
                if cells[(False, plus_total)][2] != cells[(True, plus_total)][2]
            ]
            plus_flips_for = {
                has_x2: len({cells[(has_x2, p)][2] for _, p in _PLUS_REPRESENTATIVES}) > 1
                for has_x2 in (False, True)
            }
            if x2_flip_at or any(plus_flips_for.values()):
                any_flip = True
            lines.append(
                "  x2 ever flips the verdict (plus fixed): "
                + (f"YES, at plus={x2_flip_at}" if x2_flip_at else "no")
            )
            lines.append(f"  plus ever flips the verdict (x2 fixed): {plus_flips_for}")
            lines.append("")
    lines.append(
        "Any flip found across this whole grid (both representatives): "
        + ("YES" if any_flip else "no")
    )
    text = "\n".join(lines) + "\n"
    (out / "modifier_effect.txt").write_text(text, encoding="utf-8")
    print(text)
    return 0


def _plot_basic_strategy(path: Path, table: BasicStrategyTable) -> None:
    bucket_labels = [label for label, _low, _high in PLUS_BUCKETS]
    cmap = ListedColormap(["#e15759", "#59a14f"])  # stay (red), hit (green)
    fig, axes = plt.subplots(1, 2, figsize=(7.5, 5.2), sharey=True)
    for ax, has_x2 in zip(axes, (False, True), strict=True):
        grid = np.zeros((len(UNIQUE_COUNTS), len(bucket_labels)))
        for i, unique_count in enumerate(UNIQUE_COUNTS):
            for j, bucket in enumerate(bucket_labels):
                stats = table.cells[(unique_count, has_x2, bucket)]
                grid[i, j] = 1.0 if stats.recommendation == "hit" else 0.0
                ax.text(
                    j,
                    i,
                    "HIT" if stats.recommendation == "hit" else "STAY",
                    ha="center",
                    va="center",
                    fontsize=9,
                    color="white",
                    fontweight="bold",
                )
        ax.imshow(grid, cmap=cmap, vmin=0, vmax=1, aspect="auto")
        ax.set_xticks(range(len(bucket_labels)), bucket_labels)
        ax.set_yticks(range(len(UNIQUE_COUNTS)), UNIQUE_COUNTS)
        ax.set_xlabel("plus-modifier total")
        ax.set_title(f"x2 {'held' if has_x2 else 'not held'}")
    axes[0].set_ylabel("unique number cards held")
    fig.suptitle(
        f"Flip 7 basic strategy (seed={table.seed}, samples/cell={table.samples_per_cell})"
    )
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _describe_hit_buckets(hit_buckets: set[str], bucket_order: list[str]) -> str:
    if not hit_buckets:
        return "stay"
    if hit_buckets == set(bucket_order):
        return "hit regardless of plus modifiers"
    if hit_buckets == {bucket_order[0]}:
        return "hit only with no plus modifiers"
    if hit_buckets == set(bucket_order[: len(hit_buckets)]) and bucket_order[
        len(hit_buckets) - 1
    ] != bucket_order[-1]:
        return f"hit unless plus modifiers reach {bucket_order[len(hit_buckets)]}"
    if hit_buckets == set(bucket_order[-len(hit_buckets) :]):
        return f"hit only if plus modifiers reach {bucket_order[-len(hit_buckets)]}"
    return "hit only with plus modifiers in " + ", ".join(
        b for b in bucket_order if b in hit_buckets
    )


def _write_basic_strategy_summary(
    path: Path,
    table: BasicStrategyTable,
    matchups: list[tuple[str, SimulationReport]],
) -> None:
    bucket_order = [label for label, _low, _high in PLUS_BUCKETS]
    lines = [
        f"Flip 7 basic strategy (seed={table.seed}, {table.samples_per_cell} sampled "
        "remaining decks per cell, distilled from flip7.probability.lookahead_ev)",
        "",
        "Plain-language chart:",
    ]
    for has_x2 in (False, True):
        lines.append(f"  x2 {'held' if has_x2 else 'not held'}:")
        for unique_count in UNIQUE_COUNTS:
            hit_buckets = {
                bucket
                for bucket in bucket_order
                if table.cells[(unique_count, has_x2, bucket)].recommendation == "hit"
            }
            lines.append(
                f"    {unique_count} unique card(s): "
                f"{_describe_hit_buckets(hit_buckets, bucket_order)}."
            )
    lines.append("")
    lines.append(
        "(7+ unique cards is Flip 7 -- the round already ended, there is no hit/stay choice.)"
    )
    lines.append("")
    lines.append("Cost of using this chart instead of the full lookahead_ev solver:")
    lines.append(
        f"{'vs baseline':<20} {'basic_strategy win%':>20} {'baseline win%':>16} "
        f"{'mean tot gap':>13}"
    )
    for baseline_name, report in matchups:
        n = max(report.n_games, 1)
        chal_pct = 100.0 * report.wins[0] / n
        base_pct = 100.0 * report.wins[1] / n
        tot_gap = report.mean_totals[0] - report.mean_totals[1]
        lines.append(
            f"{baseline_name:<20} {chal_pct:>19.1f}% {base_pct:>15.1f}% {tot_gap:>13.1f}"
        )
    if matchups:
        lookahead_row = next((r for name, r in matchups if name == "lookahead_ev"), None)
        if lookahead_row is not None:
            n = max(lookahead_row.n_games, 1)
            gap = 100.0 * lookahead_row.wins[1] / n - 100.0 * lookahead_row.wins[0] / n
            lines.append("")
            lines.append(
                f"Headline: against the full lookahead_ev solver 1v1, basic_strategy gives up "
                f"about {gap:.1f} percentage points of win rate "
                f"({100.0 * lookahead_row.wins[0] / n:.1f}% vs "
                f"{100.0 * lookahead_row.wins[1] / n:.1f}%, {lookahead_row.n_games} games, "
                f"seed={lookahead_row.seed})."
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _basic_strategy_matchups(
    policy: BasicStrategy,
    baselines: list[str],
    n_games: int,
    seed: int,
    target: int,
    max_rounds: int,
) -> list[tuple[str, SimulationReport]]:
    registry = named_policies()
    unknown = [name for name in baselines if name not in registry]
    if unknown:
        msg = f"unknown baseline policy names: {unknown} (known: {sorted(registry)})"
        raise SystemExit(msg)
    results: list[tuple[str, SimulationReport]] = []
    for baseline_name in baselines:
        baseline = named_policies()[baseline_name]
        report = simulate_games(
            [policy, baseline],
            n_games=n_games,
            seed=seed,
            target=target,
            max_rounds=max_rounds,
        )
        results.append((baseline_name, report))
    return results


def cmd_basic_strategy(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    table = generate_basic_strategy_table(args.seed, samples_per_cell=args.samples)
    policy = BasicStrategy(table.chart())
    baselines = [name.strip() for name in args.baselines.split(",") if name.strip()]
    matchups = _basic_strategy_matchups(
        policy,
        baselines,
        args.games,
        args.seed,
        args.target,
        args.max_rounds,
    )
    _plot_basic_strategy(out / "basic_strategy.png", table)
    _write_basic_strategy_summary(out / "basic_strategy.txt", table, matchups)
    print((out / "basic_strategy.txt").read_text(encoding="utf-8"))
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

    basic = sub.add_parser(
        "basic-strategy",
        help="Generate the memorizable basic-strategy chart and measure its cost vs lookahead_ev",
    )
    basic.add_argument("--seed", type=int, default=1)
    basic.add_argument("--out", type=str, default="reports")
    basic.add_argument(
        "--samples",
        type=int,
        default=60,
        help="lookahead_ev samples averaged per chart cell (42 cells; higher is slower)",
    )
    basic.add_argument(
        "--games",
        type=int,
        default=200,
        help="Games per 1v1 matchup used to measure the win-rate/EV gap",
    )
    basic.add_argument(
        "--baselines",
        type=str,
        default=",".join(DEFAULT_BASIC_STRATEGY_BASELINES),
        help="Comma-separated baseline policy names to measure basic_strategy against",
    )
    basic.add_argument(
        "--target",
        type=int,
        default=TARGET_SCORE,
        help="Race-to score (lower it for a quick smoke run, e.g. --target 1 --max-rounds 2)",
    )
    basic.add_argument("--max-rounds", type=int, default=400, dest="max_rounds")
    basic.set_defaults(func=cmd_basic_strategy)

    replay = sub.add_parser(
        "replay",
        help="Print a turn-by-turn trace of one game for manual rule verification",
    )
    replay.add_argument("--seed", type=int, default=1)
    replay.add_argument("--out", type=str, default="reports")
    replay.add_argument(
        "--policies",
        type=str,
        default=None,
        help="Comma-separated policy names (see 'flip7 policies'); default: 3x stay_after_deal",
    )
    replay.add_argument(
        "--deck",
        type=int,
        choices=(85, 94),
        default=85,
        help="85 (Phase 1, no action cards) or 94 (Phase 2, with Freeze/Flip Three/Second Chance)",
    )
    replay.add_argument("--target", type=int, default=TARGET_SCORE)
    replay.add_argument("--max-rounds", type=int, default=400, dest="max_rounds")
    replay.set_defaults(func=cmd_replay)

    modifier_effect = sub.add_parser(
        "modifier-effect",
        help=(
            "Issue #13 concern 2: exact, deterministic check of whether x2/plus "
            "modifiers ever flip the basic-strategy hit/stay verdict"
        ),
    )
    modifier_effect.add_argument("--out", type=str, default="reports")
    modifier_effect.set_defaults(func=cmd_modifier_effect)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))
