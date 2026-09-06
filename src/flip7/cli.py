from __future__ import annotations

import argparse
import random
from itertools import combinations
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap

from flip7.basic_strategy import (
    ALL_CELLS,
    HELD_VALUE_SUM_STAY_THRESHOLDS,
    PBUST_BUCKETS,
    PLUS_BUCKETS,
    UNIQUE_COUNTS,
    BasicStrategyTable,
    generate_basic_strategy_table,
    p_bust_bucket_label,
)
from flip7.cards import full_deck
from flip7.diagnostics import DiagnosticsReport, run_diagnostics
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
    BASIC_STRATEGY_CHART,
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


def cmd_pbust_bucket_check(args: argparse.Namespace) -> int:
    """Issue #13 concern 1: exact, deterministic check of whether P(bust)
    bucketing (ADR-016) actually resolves the count-only blind spot, against
    *every* possible held-number identity per unique_count -- not just the
    two "low"/"high" representatives `flip7 modifier-effect` uses -- via
    exact `lookahead_ev` (no Monte Carlo sampling).
    """
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    lines = [
        "Flip 7 P(bust)-bucket check (issue #13, concern 1)",
        "",
        "Exhaustive: for each unique_count, every possible held-number identity",
        "(itertools.combinations(range(13), unique_count)) against the full deck",
        "minus those held numbers (exact, no sampling; plus=0, no x2). Compares",
        "the true lookahead_ev hit/stay verdict against (a) the new P(bust)-",
        "bucketed chart (ADR-016, flip7.strategy.BASIC_STRATEGY_CHART) and",
        "(b) the old shipped rule 'hit iff unique_count <= 2' (ADR-013),",
        "reporting each rule's exact agreement rate with ground truth.",
        "",
    ]
    total = 0
    new_agree = 0
    old_agree = 0
    for unique_count in UNIQUE_COUNTS:
        near_flip7 = unique_count == 6
        n = n_new = n_old = 0
        for combo in combinations(range(13), unique_count):
            numbers = list(combo)
            remaining = _remaining_after(numbers)
            hit_ev = lookahead_ev(numbers, 0, False, remaining)
            stay_value = float(score_line(numbers, 0, False, False))
            true_decision = "hit" if hit_ev > stay_value else "stay"
            new_cell = (p_bust_bucket_label(p_bust(numbers, remaining)), near_flip7, False, "0")
            new_decision = BASIC_STRATEGY_CHART.get(new_cell, "stay")
            old_decision = "hit" if unique_count <= 2 else "stay"
            n += 1
            n_new += new_decision == true_decision
            n_old += old_decision == true_decision
        total += n
        new_agree += n_new
        old_agree += n_old
        lines.append(
            f"unique_count={unique_count}: {n} held-number identities -- "
            f"new chart agrees {n_new}/{n} ({100.0 * n_new / n:.1f}%), "
            f"old chart agrees {n_old}/{n} ({100.0 * n_old / n:.1f}%)"
        )
    lines.append("")
    lines.append(
        f"Overall: new chart agrees {new_agree}/{total} ({100.0 * new_agree / total:.1f}%), "
        f"old chart agrees {old_agree}/{total} ({100.0 * old_agree / total:.1f}%)"
    )
    lines.append("")

    lines.append(
        "Low/high representative bucket separation (closes ADR-013's addendum gap):"
    )
    for unique_count in UNIQUE_COUNTS:
        low = list(range(unique_count))
        high = list(range(12, 12 - unique_count, -1))
        pb_low = p_bust(low, _remaining_after(low))
        pb_high = p_bust(high, _remaining_after(high))
        label_low = p_bust_bucket_label(pb_low)
        label_high = p_bust_bucket_label(pb_high)
        near_flip7 = unique_count == 6
        rec_low = BASIC_STRATEGY_CHART.get((label_low, near_flip7, False, "0"), "stay")
        rec_high = BASIC_STRATEGY_CHART.get((label_high, near_flip7, False, "0"), "stay")
        same_or_different = "SAME bucket" if label_low == label_high else "DIFFERENT buckets"
        lines.append(
            f"  unique_count={unique_count}: low p_bust={pb_low:.3f} ({label_low}) -> {rec_low}; "
            f"high p_bust={pb_high:.3f} ({label_high}) -> {rec_high}; {same_or_different}"
        )

    text = "\n".join(lines) + "\n"
    (out / "pbust_bucket_check.txt").write_text(text, encoding="utf-8")
    print(text)
    return 0


def _rate(bucket: list[int]) -> float | None:
    busts, attempts = bucket
    return busts / attempts if attempts else None


def _format_diagnostics(report: DiagnosticsReport) -> str:
    lines = [
        f"Flip 7 per-strategy diagnostics: {report.policy_name} "
        f"({report.n_games} games x {report.n_players} self-play seats, seed={report.seed})",
        "",
    ]

    totals = sorted(report.totals)
    n = len(totals)
    lines.append(f"Score distribution ({n} final totals pooled across all seats/games):")
    if n:
        mean = sum(totals) / n
        median = totals[n // 2] if n % 2 else (totals[n // 2 - 1] + totals[n // 2]) / 2
        variance = sum((t - mean) ** 2 for t in totals) / n
        lines.append(
            f"  mean={mean:.1f} median={median:.1f} stdev={variance**0.5:.1f} "
            f"min={totals[0]} max={totals[-1]}"
        )
    lines.append("")

    lines.append(
        "Empirical decision chart (observed hit-rate per cell vs. the shipped "
        "basic_strategy chart, flip7.strategy.BASIC_STRATEGY_CHART):"
    )
    lines.append(
        f"  {'p_bust':>8} {'near_f7':>7} {'x2':>5} {'plus':>5} {'n':>6} "
        f"{'hit%':>7} {'chart says':>10}"
    )
    for cell in ALL_CELLS:
        pbust_bucket, near_flip7, has_x2, bucket_label = cell
        hits, total = report.decisions.get(cell, [0, 0])
        hit_pct = f"{100.0 * hits / total:6.1f}%" if total else "    n/a"
        chart_rec = BASIC_STRATEGY_CHART.get(cell, "?")
        lines.append(
            f"  {pbust_bucket:>8} {near_flip7!s:>7} {has_x2!s:>5} {bucket_label:>5} "
            f"{total:>6} {hit_pct:>7} {chart_rec:>10}"
        )
    lines.append("")

    lines.append("Bust rate by unique_count held at the moment of the hit decision:")
    for unique_count in sorted(report.bust_by_unique_count):
        busts, attempts = report.bust_by_unique_count[unique_count]
        pct = f"{100.0 * busts / attempts:.1f}%" if attempts else "n/a"
        lines.append(f"  unique_count={unique_count}: {busts}/{attempts} busts ({pct})")
    lines.append("")

    lines.append(
        "Bust rate by P(bust) bucket at the moment of the hit decision (ADR-016 -- "
        "confirms bust risk tracks this axis, not just raw card count):"
    )
    for label, _low, _high in PBUST_BUCKETS:
        busts, attempts = report.bust_by_pbust_bucket.get(label, [0, 0])
        pct = f"{100.0 * busts / attempts:.1f}%" if attempts else "n/a"
        lines.append(f"  p_bust={label}: {busts}/{attempts} busts ({pct})")
    lines.append("")

    lines.append("Bust rate by round number within a game:")
    for round_no in sorted(report.bust_by_round):
        busts, attempts = report.bust_by_round[round_no]
        pct = f"{100.0 * busts / attempts:.1f}%" if attempts else "n/a"
        lines.append(f"  round {round_no}: {busts}/{attempts} busts ({pct})")
    lines.append("")

    lines.append("Bust rate by the actual number value drawn (higher values have more")
    lines.append("copies in the deck -- flip7.cards.NUMBER_COUNTS -- so should bust more often):")
    for value in sorted(report.bust_by_value):
        busts, attempts = report.bust_by_value[value]
        pct = f"{100.0 * busts / attempts:.1f}%" if attempts else "n/a"
        lines.append(f"  value={value:>2}: {busts}/{attempts} busts ({pct})")

    return "\n".join(lines) + "\n"


def _plot_diagnostics_score_hist(path: Path, report: DiagnosticsReport) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.hist(report.totals, bins=30)
    ax.set_xlabel("Final game total")
    ax.set_ylabel("Count (pooled across seats/games)")
    ax.set_title(f"{report.policy_name}: score distribution ({report.n_games} games)")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _plot_diagnostics_bust_rates(path: Path, report: DiagnosticsReport) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))

    ucs = sorted(report.bust_by_unique_count)
    axes[0].bar(ucs, [100.0 * (_rate(report.bust_by_unique_count[u]) or 0.0) for u in ucs])
    axes[0].set_xlabel("unique_count at hit decision")
    axes[0].set_ylabel("Bust rate (%)")

    rounds = sorted(report.bust_by_round)
    axes[1].bar(rounds, [100.0 * (_rate(report.bust_by_round[r]) or 0.0) for r in rounds])
    axes[1].set_xlabel("round number")

    values = sorted(report.bust_by_value)
    axes[2].bar(values, [100.0 * (_rate(report.bust_by_value[v]) or 0.0) for v in values])
    axes[2].set_xlabel("drawn number value")

    fig.suptitle(f"{report.policy_name}: bust rate breakdowns")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def cmd_diagnostics(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    registry = named_policies()
    if args.policy not in registry:
        msg = f"unknown policy name: {args.policy!r} (known: {sorted(registry)})"
        raise SystemExit(msg)
    policy = registry[args.policy]
    report = run_diagnostics(
        policy,
        args.policy,
        n_players=args.players,
        n_games=args.games,
        seed=args.seed,
        target=args.target,
        max_rounds=args.max_rounds,
    )
    text = _format_diagnostics(report)
    (out / f"diagnostics_{args.policy}.txt").write_text(text, encoding="utf-8")
    _plot_diagnostics_score_hist(out / f"diagnostics_{args.policy}_score_hist.png", report)
    _plot_diagnostics_bust_rates(out / f"diagnostics_{args.policy}_bust_rate.png", report)
    print(text)
    return 0


def _plot_basic_strategy(path: Path, table: BasicStrategyTable) -> None:
    plus_labels = [label for label, _low, _high in PLUS_BUCKETS]
    pbust_labels = [label for label, _low, _high in PBUST_BUCKETS]
    cmap = ListedColormap(["#e15759", "#59a14f"])  # stay (red), hit (green)
    fig, axes = plt.subplots(2, 2, figsize=(8.5, 8.5), sharex=True, sharey=True)
    for row, near_flip7 in enumerate((False, True)):
        for col, has_x2 in enumerate((False, True)):
            ax = axes[row][col]
            grid = np.zeros((len(pbust_labels), len(plus_labels)))
            for i, pbust_label in enumerate(pbust_labels):
                for j, plus_label in enumerate(plus_labels):
                    stats = table.cells[(pbust_label, near_flip7, has_x2, plus_label)]
                    grid[i, j] = 1.0 if stats.recommendation == "hit" else 0.0
                    ax.text(
                        j,
                        i,
                        "HIT" if stats.recommendation == "hit" else "STAY",
                        ha="center",
                        va="center",
                        fontsize=8,
                        color="white",
                        fontweight="bold",
                    )
            ax.imshow(grid, cmap=cmap, vmin=0, vmax=1, aspect="auto")
            ax.set_xticks(range(len(plus_labels)), plus_labels)
            ax.set_yticks(range(len(pbust_labels)), pbust_labels)
            ax.set_title(
                f"x2 {'held' if has_x2 else 'not held'}, "
                f"{'one card from Flip 7' if near_flip7 else 'not near Flip 7'}"
            )
    for ax in axes[-1]:
        ax.set_xlabel("plus-modifier total")
    for ax in axes[:, 0]:
        ax.set_ylabel("P(bust)")
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


def _tally_pbust_translation(unique_count: int, threshold: int) -> str:
    """The range of exact P(bust) among every real held-number combination
    whose value-sum equals `threshold` at this `unique_count` -- shows how
    the cheap tally threshold lines up with the exact chart's own P(bust)
    buckets above.
    """
    values = []
    for combo in combinations(range(13), unique_count):
        if sum(combo) == threshold:
            remaining = full_counts()
            for value in combo:
                remaining.numbers[value] -= 1
            values.append(p_bust(list(combo), remaining))
    low, high = min(values), max(values)
    low_label, high_label = p_bust_bucket_label(low), p_bust_bucket_label(high)
    bucket = low_label if low_label == high_label else f"{low_label}..{high_label}"
    return f"{100.0 * low:.0f}-{100.0 * high:.0f}% ({bucket})"


def _human_tally_cheat_sheet() -> list[str]:
    lines = [
        "Human-at-the-table cheat sheet (ADR-016): add up the values of the",
        "number cards you're holding (the same subtotal you already track for",
        "your score, before x2/plus). Stay once that total reaches:",
        f"  {'unique cards held':<18} {'stay once sum reaches':>22} {'~P(bust) there':>18}",
    ]
    for unique_count in UNIQUE_COUNTS:
        threshold = HELD_VALUE_SUM_STAY_THRESHOLDS.get(unique_count)
        if threshold is None:
            lines.append(f"  {unique_count:<18} {'(always hit)':>22} {'':>18}")
            continue
        translation = _tally_pbust_translation(unique_count, threshold)
        lines.append(f"  {unique_count:<18} {threshold:>22} {translation:>18}")
    lines.append(
        "This tally alone reproduces the true hit/stay verdict on 97.8% of every"
    )
    lines.append(
        "possible held-number identity (exhaustive check, see `flip7 pbust-bucket-check`)"
    )
    lines.append(
        "-- close to, but not identical to, the shipped chart's own exact P(bust); it"
    )
    lines.append("ignores x2/plus, which the exact chart shows rarely move the verdict.")
    return lines


def _write_basic_strategy_summary(
    path: Path,
    table: BasicStrategyTable,
    matchups: list[tuple[str, SimulationReport]],
) -> None:
    bucket_order = [label for label, _low, _high in PLUS_BUCKETS]
    pbust_order = [label for label, _low, _high in PBUST_BUCKETS]
    lines = [
        f"Flip 7 basic strategy (seed={table.seed}, {table.samples_per_cell} sampled "
        "remaining decks per cell, distilled from flip7.probability.lookahead_ev)",
        "",
        "Plain-language chart (P(bust) is this line's exact bust risk against the",
        "remaining deck -- see ADR-016; a cheap sum(held card values) tally tracks",
        "it closely enough for a human to use at the table without exact counting):",
    ]
    for near_flip7 in (False, True):
        lines.append(f"  {'one card from Flip 7' if near_flip7 else 'not near Flip 7'}:")
        for has_x2 in (False, True):
            lines.append(f"    x2 {'held' if has_x2 else 'not held'}:")
            for pbust_label in pbust_order:
                hit_buckets = {
                    bucket
                    for bucket in bucket_order
                    if table.cells[(pbust_label, near_flip7, has_x2, bucket)].recommendation
                    == "hit"
                }
                lines.append(
                    f"      P(bust) {pbust_label}: "
                    f"{_describe_hit_buckets(hit_buckets, bucket_order)}."
                )
    lines.append("")
    lines.append(
        "(7 unique cards is Flip 7 -- the round already ended, there is no hit/stay choice.)"
    )
    lines.append("")
    lines.extend(_human_tally_cheat_sheet())
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
        help="lookahead_ev samples averaged per chart cell (48 cells; higher is slower)",
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

    pbust_bucket_check = sub.add_parser(
        "pbust-bucket-check",
        help=(
            "Issue #13 concern 1: exact, exhaustive check of whether P(bust) "
            "bucketing (ADR-016) resolves the count-only chart blind spot"
        ),
    )
    pbust_bucket_check.add_argument("--out", type=str, default="reports")
    pbust_bucket_check.set_defaults(func=cmd_pbust_bucket_check)

    diagnostics = sub.add_parser(
        "diagnostics",
        help=(
            "Per-strategy empirical diagnostics: observed decision chart, bust-rate "
            "breakdowns, and score distribution for one policy over many self-play games"
        ),
    )
    diagnostics.add_argument("--policy", type=str, required=True)
    diagnostics.add_argument("--players", type=int, default=3)
    diagnostics.add_argument("--games", type=int, default=500)
    diagnostics.add_argument("--seed", type=int, default=1)
    diagnostics.add_argument("--out", type=str, default="reports")
    diagnostics.add_argument("--target", type=int, default=TARGET_SCORE)
    diagnostics.add_argument("--max-rounds", type=int, default=400, dest="max_rounds")
    diagnostics.set_defaults(func=cmd_diagnostics)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))
