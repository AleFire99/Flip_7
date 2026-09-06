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
By default it seats `stay_after_deal`, `chase_flip7`, and `one_step_ev`. Pass
`--policies` (comma-separated, see `flip7 policies`) for any other mixed seating,
e.g. `--policies stay_after_deal,one_step_ev,lookahead_ev`.

Other commands:

```bash
uv run flip7 ev-table --seed 1
uv run flip7 policies
uv run flip7 --help
```

## Policies

- `stay_after_deal` -- always banks the opening card.
- `chase_flip7` -- always hits.
- `bust_tau_0.25` / `bust_tau_0.40` -- stays once P(bust) reaches the threshold.
- `one_step_ev` -- **analysis option A**: hits iff the expected score after
  exactly one more card, then banking, exceeds the current score. Myopic: it
  never values a *second* hit (ADR-008).
- `lookahead_ev` -- **analysis option B** (ADR-003/ADR-009): hits iff the
  recursive DP expected value of hitting exceeds the current score. Unlike
  `one_step_ev`, at every hypothetical future state it again picks
  `max(stay, hit)`, so it correctly values "hit again if the next card is
  safe" chains. It is provably never worse-informed than `one_step_ev`
  (`flip7.probability.lookahead_ev(...) >= one_step_ev(...)` always -- see
  `tests/test_probability.py`). It still assumes no other seat draws further
  cards from this point on (i.e. it is the optimal *solo* policy against the
  remaining deck, not a model of opponents -- that's a separate, later piece
  of work).

  **Performance note:** `lookahead_ev` solves an optimal hit/stay policy from
  scratch on every decision by recursing over the remaining deck, so it is
  much slower than the other policies (well under a second once a few cards
  are held, but roughly 1-2 seconds for a decision made with an empty hand
  against a near-full deck). Simulations that include it will run noticeably
  slower than pure option-A comparisons.

## Compare

```bash
uv run flip7 compare --games 100 --seed 1 --out reports
```

Runs every registered policy 1v1 (`[challenger, baseline]`, two seats) against
each of `stay_after_deal`, `chase_flip7`, and `one_step_ev` in turn, and writes
`reports/compare.txt` with a win-rate table per baseline -- this is how
`lookahead_ev` is measured against the option-A policies. Useful flags:

- `--baselines stay_after_deal,one_step_ev` -- restrict which baselines to run.
- `--policies lookahead_ev,one_step_ev` -- restrict which challengers to run.
- `--target 1 --max-rounds 2` -- race to a trivial target instead of 200, for a
  quick smoke run (handy since `lookahead_ev` matchups are the slow ones above).

## Git Flow

- `main` — stable releases
- `develop` — integration branch
- `feature/*` — one issue per branch, PR into `develop`
- Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`, `chore:`
