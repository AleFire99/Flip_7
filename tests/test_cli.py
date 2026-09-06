from __future__ import annotations

from pathlib import Path

from flip7.cli import build_parser, cmd_analyze, cmd_basic_strategy, cmd_compare, cmd_ev_table


def test_parser_analyze_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args(["analyze", "--games", "2", "--seed", "0"])
    assert args.games == 2
    assert args.command == "analyze"


def test_ev_table_runs(capsys) -> None:
    args = build_parser().parse_args(["ev-table", "--seed", "2"])
    assert cmd_ev_table(args) == 0
    out = capsys.readouterr().out
    assert "one-step EV" in out
    assert "lookahead EV" in out


def test_analyze_accepts_custom_policies_list(tmp_path: Path, capsys) -> None:
    args = build_parser().parse_args(
        [
            "analyze",
            "--games",
            "2",
            "--seed",
            "0",
            "--out",
            str(tmp_path),
            "--policies",
            "stay_after_deal,chase_flip7,one_step_ev,bust_tau_0.25",
        ]
    )
    assert cmd_analyze(args) == 0
    out = capsys.readouterr().out
    assert "bust_tau_0.25" in out


def test_analyze_rejects_unknown_policy_name(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        [
            "analyze",
            "--games",
            "2",
            "--out",
            str(tmp_path),
            "--policies",
            "not_a_real_policy",
        ]
    )
    try:
        cmd_analyze(args)
    except SystemExit as exc:
        assert "unknown policy names" in str(exc)
    else:
        raise AssertionError("expected SystemExit for an unknown policy name")


def test_compare_runs_all_policies_against_default_baselines(tmp_path: Path, capsys) -> None:
    args = build_parser().parse_args(
        [
            "compare",
            "--games",
            "2",
            "--seed",
            "0",
            "--out",
            str(tmp_path),
            # lookahead_ev is slow; race to a trivial target so this stays fast.
            "--target",
            "1",
            "--max-rounds",
            "2",
        ]
    )
    assert cmd_compare(args) == 0
    out = capsys.readouterr().out
    for baseline in ("stay_after_deal", "chase_flip7", "one_step_ev"):
        assert f"vs {baseline}" in out
    assert "lookahead_ev" in out
    assert (tmp_path / "compare.txt").exists()


def test_compare_accepts_custom_baselines_and_policies(tmp_path: Path, capsys) -> None:
    args = build_parser().parse_args(
        [
            "compare",
            "--games",
            "2",
            "--seed",
            "0",
            "--out",
            str(tmp_path),
            "--baselines",
            "one_step_ev",
            "--policies",
            "lookahead_ev,one_step_ev",
            "--target",
            "1",
            "--max-rounds",
            "2",
        ]
    )
    assert cmd_compare(args) == 0
    out = capsys.readouterr().out
    assert "vs one_step_ev" in out
    assert "chase_flip7" not in out


def test_basic_strategy_runs_and_writes_outputs(tmp_path: Path, capsys) -> None:
    args = build_parser().parse_args(
        [
            "basic-strategy",
            "--seed",
            "0",
            "--out",
            str(tmp_path),
            "--samples",
            "1",
            "--games",
            "2",
            "--baselines",
            "stay_after_deal,one_step_ev",
            "--target",
            "1",
            "--max-rounds",
            "2",
        ]
    )
    assert cmd_basic_strategy(args) == 0
    out = capsys.readouterr().out
    assert "basic strategy" in out.lower()
    assert "stay_after_deal" in out
    assert "one_step_ev" in out
    assert (tmp_path / "basic_strategy.txt").exists()
    assert (tmp_path / "basic_strategy.png").exists()


def test_basic_strategy_headline_names_lookahead_ev_when_included(
    tmp_path: Path, capsys
) -> None:
    args = build_parser().parse_args(
        [
            "basic-strategy",
            "--seed",
            "0",
            "--out",
            str(tmp_path),
            "--samples",
            "1",
            "--games",
            "2",
            "--baselines",
            "lookahead_ev",
            "--target",
            "1",
            "--max-rounds",
            "2",
        ]
    )
    assert cmd_basic_strategy(args) == 0
    out = capsys.readouterr().out
    assert "Headline" in out
    assert "lookahead_ev" in out


def test_basic_strategy_rejects_unknown_baseline(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        [
            "basic-strategy",
            "--out",
            str(tmp_path),
            "--samples",
            "1",
            "--games",
            "1",
            "--baselines",
            "not_a_real_policy",
            "--target",
            "1",
            "--max-rounds",
            "1",
        ]
    )
    try:
        cmd_basic_strategy(args)
    except SystemExit as exc:
        assert "unknown baseline policy" in str(exc)
    else:
        raise AssertionError("expected SystemExit for an unknown baseline policy name")
