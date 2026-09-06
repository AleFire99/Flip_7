from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from random import Random

from flip7.basic_strategy import Cell, plus_bucket_label
from flip7.engine import Policy, TraceEvent, play_game
from flip7.scoring import TARGET_SCORE


@dataclass
class DiagnosticsReport:
    """Empirical, many-games behavior of one policy (issue #14).

    Everything here is observed from real simulated games (via the
    ``"decide"`` `TraceEvent`s issue #14 added to `play_round`), not computed
    analytically the way `flip7.basic_strategy`'s chart or
    `flip7.probability.p_bust` are -- the point is to check whether a
    policy's actual behavior matches its design intent.
    """

    policy_name: str
    n_games: int
    n_players: int
    seed: int
    #: cell -> (hit decisions, total decisions) at that (unique_count capped
    #: at 6, has_x2, plus_bucket) cell -- the empirical counterpart to
    #: `flip7.basic_strategy.ALL_CELLS`.
    decisions: dict[Cell, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    #: unique_count (at decision time) -> (busts, hit attempts)
    bust_by_unique_count: dict[int, list[int]] = field(
        default_factory=lambda: defaultdict(lambda: [0, 0])
    )
    #: round number within a game -> (busts, hit attempts)
    bust_by_round: dict[int, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    #: drawn number value -> (busts, times this value was actually drawn)
    bust_by_value: dict[int, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    #: every seat's final total, every game (pooled across seats: self-play,
    #: same policy in every seat, so this is the policy's score distribution).
    totals: list[int] = field(default_factory=list)


def _cell_for(unique_count: int, has_x2: bool, plus: int) -> Cell:
    return (min(unique_count, 6), has_x2, plus_bucket_label(plus))


def _find_own_draw(trace: list[TraceEvent], start: int, seat: int) -> TraceEvent | None:
    """The event immediately after a ``"decide"`` event that recorded
    ``seat``'s own draw outcome. Always exactly the next event in practice
    (`_draw_and_resolve` logs it before any nested Flip Three draws for a
    *different* seat), but this scans forward defensively rather than
    indexing blindly.
    """
    for later in trace[start : start + 3]:
        if later.seat == seat and later.kind == "hit":
            return later
    return None


def process_trace(report: DiagnosticsReport, trace: list[TraceEvent]) -> None:
    for i, event in enumerate(trace):
        if event.kind != "decide":
            continue
        assert event.state_unique_count is not None
        assert event.state_has_x2 is not None
        assert event.state_plus is not None
        cell = _cell_for(event.state_unique_count, event.state_has_x2, event.state_plus)
        counts = report.decisions[cell]
        counts[1] += 1
        if event.decision != "hit":
            continue
        counts[0] += 1

        draw = _find_own_draw(trace, i + 1, event.seat)  # type: ignore[arg-type]
        if draw is None:
            continue
        busted = draw.outcome == "bust"

        uc_bucket = report.bust_by_unique_count[event.state_unique_count]
        uc_bucket[1] += 1
        uc_bucket[0] += busted

        round_bucket = report.bust_by_round[event.round_no]
        round_bucket[1] += 1
        round_bucket[0] += busted

        if draw.card is not None and draw.card.isdigit():
            value_bucket = report.bust_by_value[int(draw.card)]
            value_bucket[1] += 1
            value_bucket[0] += busted


def run_diagnostics(
    policy: Policy,
    policy_name: str,
    *,
    n_players: int = 3,
    n_games: int = 500,
    seed: int = 1,
    target: int = TARGET_SCORE,
    max_rounds: int = 400,
) -> DiagnosticsReport:
    """Run `n_games` self-play games (`policy` in every seat) and aggregate
    the real hit/stay decisions and their outcomes (issue #14).

    A fresh `trace` list is built and processed per game rather than one
    list across all games, so memory stays bounded by one game's worth of
    events instead of growing with `n_games`.
    """
    rng = Random(seed)
    report = DiagnosticsReport(
        policy_name=policy_name, n_games=n_games, n_players=n_players, seed=seed
    )
    policies = [policy] * n_players
    for _ in range(n_games):
        trace: list[TraceEvent] = []
        result = play_game(
            policies, rng, target=target, max_rounds=max_rounds, trace=trace
        )
        report.totals.extend(result.totals)
        process_trace(report, trace)
    return report
