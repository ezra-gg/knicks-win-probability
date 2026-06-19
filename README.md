# 🏀 Knicks Win Probability

A win-probability model trained on historical NBA play-by-play data, with an
interactive Streamlit app that lets you scrub through any game and watch the
live probability curve. Knicks will always steal the spotlight though.

> Ezra's first just-for-fun project.
> Leveraging Claude Code to accelerate the development, but owning all key architecture and design decisions.

## How it works

Game results and play-by-play come from the public NBA stats API (via
[`nba_api`](https://github.com/swar/nba_api)), land in a local DuckDB database,
and feed a calibrated classifier. Given the score, time remaining, and period
at any point in a game, the model estimates each team's chance of winning, and
the Streamlit app replays that estimate across the whole game.

## Try the app

The trained model and a compact data slice are committed, so the Streamlit app
runs straight from a clone - no data pull, no training:

```bash
pip install -r app/requirements.txt
just app          # or: streamlit run app/streamlit_app.py
```

It opens two views: a **game replay** (the win-probability curve through any
recent game) and a **matchup calculator** (any two teams at any game state).

## Rebuild from scratch

Requires Python 3.12+. To regenerate everything from source:

```bash
# 1. Set up the virtual environment and install dependencies
./scripts/setup.sh

# 2. Pull data (game index + play-by-play) through the current season
./scripts/ingest.sh --start-season 2023-24

# 3. Load, build, rate, train, and export serving artifacts
just pipeline
```

Re-running `ingest.sh` is incremental. It skips games already on disk and only
fetches what's new, so it's safe to interrupt and resume.

## Roadmap

- [x] Data ingestion (game index + play-by-play)
- [x] Local DuckDB storage
- [x] Feature engineering (dbt: staging -> intermediate -> mart)
- [x] Team strength ratings (Elo, validated against Net Rating and SRS)
- [x] Model training and calibration (logistic baseline + XGBoost)
- [x] Matchup predictor + Streamlit app (game replay + matchup calculator)
- [ ] Live game listener (stream an in-progress game, update the curve in real time)
- [ ] Player-aware team strength (see "Down the road")

See [docs/RUNBOOK.md](docs/RUNBOOK.md) to run the pipeline and
[docs/MAINTENANCE.md](docs/MAINTENANCE.md) to keep it healthy.

## Down the road

**Next up: a live game listener.** Poll an in-progress game from the NBA's live
play-by-play feed, track the clock and score, and update the win-probability curve
in real time - turning the game-replay view into a live scoreboard. The
`MatchupPredictor` is already built to be called once per update; the listener is
the piece that feeds it live state.

A few further directions I want to explore now that the core model works:

- **Roster-aware season transitions (in progress).** Instead of carrying a team's
  Elo into the next season unchanged, regress it toward the mean by how much of the
  roster turned over. Continuity is the fraction of last season's scoring production
  that returned (`int_roster_continuity`), so a gutted team drops and a team that kept
  its core does not. A first version weighted by scoring share is being built; the
  richer player-value version below is the natural successor.
- **Learned player value (RAPM).** Scoring share is an offense-only proxy: it misses
  defenders and playmakers. The plan is to learn each player's value from outcomes
  rather than the box score, with **Regularized Adjusted Plus-Minus** - regress
  possession point-differential on which five players are on the court, so a player
  who never scores but tilts the game still earns credit. The build:
  1. Reconstruct five-man lineups from the play-by-play substitution events (already
     ingested; ~1.3M of them).
  2. Compute RAPM per player per season - our own values, all 26 seasons, one
     consistent measure (no historical coverage gap).
  3. Validate against the NBA's official player-tracking metrics (2013-14+) as a
     convergent-validity check, the same way our Elo was checked against Net Rating
     and SRS. A sanity test, not a feature source.
  4. Optionally feed the official tracking metrics in as supplementary features for
     the seasons they cover; XGBoost handles their absence in older seasons natively,
     and the holdout sits entirely in the tracked era. Run as a measured experiment.
- **Player-aware team strength.** With per-player values in hand, build team strength
  as the current roster's summed value instead of one franchise Elo number, so a
  mid-season trade reprices the team immediately.
- **Provisional ratings.** A faster-moving rating early in a team's history to cut
  down on cold-start noise in the earliest seasons.

## Tech stack

| Layer            | Tool                      |
| ---------------- | ------------------------- |
| Data source      | `nba_api`                 |
| Storage          | `DuckDB`                  |
| Transformation   | `dbt` (`dbt-duckdb`)      |
| Data processing  | `pandas`                  |
| Modeling         | `scikit-learn`, `XGBoost` |
| Task running     | `just`                    |
| App              | `Streamlit`               |

## Project layout

```
knicks-win-probability/
├── scripts/       # setup and run wrappers (setup.sh, ingest.sh, load.sh, ...)
├── src/           # ingestion, Elo ratings, validation, model training
├── transform/     # dbt project (staging -> intermediate -> mart, + tests)
├── tests/         # pytest unit tests
├── docs/          # runbook and maintenance guide
├── data/          # raw CSVs and the DuckDB database (gitignored)
├── notebooks/     # exploratory analysis
├── app/           # Streamlit dashboard
├── models/        # trained model artifacts
├── params.yml     # all tunables (Elo, model features, split windows, hyperparams)
└── justfile       # task runner (just ingest / load / ratings / dbt / train / full)
```

## Notes

`nba_api` is an unofficial client for stats.nba.com. This project isn't
affiliated with or endorsed by the NBA, and is meant for personal and
educational use.
