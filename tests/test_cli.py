from __future__ import annotations

from flip7.cli import build_parser, cmd_ev_table


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
