# Flip 7 strategy analysis

Python workspace for studying **Flip 7** with exact remaining-deck probabilities and Monte Carlo games.

Phase 1 models **number cards and score modifiers only** (no Freeze, Flip Three, or Second Chance). See [docs/RULES_PHASE1.md](docs/RULES_PHASE1.md) and [docs/DECISIONS.md](docs/DECISIONS.md).

Phase 2 adds the official **Freeze, Flip Three, and Second Chance** action cards as an engine plugin on a 94-card deck. See [docs/RULES_PHASE2.md](docs/RULES_PHASE2.md).

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
uv sync --group dev
uv run pytest
uv run ruff check src tests
```

## Analyze

```bash
uv run flip7 analyze --games 2000 --seed 1 --out reports
```

This writes `reports/summary.txt`, `reports/win_rates.png`, and `reports/round_stats.png`.

Other commands:

```bash
uv run flip7 ev-table --seed 1
uv run flip7 --help
```

## Git Flow

- `main` — stable releases
- `develop` — integration branch
- `feature/*` — one issue per branch, PR into `develop`
- Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`, `chore:`
