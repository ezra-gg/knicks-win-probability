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

**[ezra-nba-probability.streamlit.app](https://ezra-nba-probability.streamlit.app/)** - no install needed.

Three views: an **overview** (one team's tip-off odds against the whole league),
a **matchup drill-down** (any two teams at any game state), and a **game replay**
(the win-probability curve through any historical game, plotted across the four
quarters with a perspective toggle to follow either team's odds).

To run locally instead:

```bash
pip install -r app/requirements.txt
streamlit run app/streamlit_app.py
```

## Rebuild from scratch

> **Platform note:** the data pipeline currently requires macOS or Linux. The
> pipeline scripts are bash-based and the justfile uses Unix virtualenv paths.
> Windows support is not planned, but the app can be enjoyed without local 
> download on Streamlit Community Cloud.

Requires Python 3.12+. To regenerate everything from source:

```bash
# 1. Set up the virtual environment and install dependencies
./scripts/setup.sh

# 2. Pull data through the current season: game index + play-by-play, then the
#    box scores the player-value models need (both default to 2000-01 onward)
just ingest
just ingest-boxscores

# 3. Load, build, rate, train, and export serving artifacts
just pipeline
```

Or run the whole thing - pull, rebuild, retrain, export - with `just full`.

Re-running `ingest.sh` is incremental. It skips games already on disk and only
fetches what's new, so it's safe to interrupt and resume.

## Roadmap

- [x] Data ingestion (game index + play-by-play)
- [x] Local DuckDB storage
- [x] Feature engineering (dbt: staging -> intermediate -> mart)
- [x] Team strength ratings (Elo, validated against Net Rating and SRS)
- [x] Model training and calibration (logistic baseline + XGBoost)
- [x] Matchup predictor + Streamlit app (overview, matchup drill-down, game replay)
- [x] Player-aware team strength (learned RAPM + box-score roster value)
- [ ] Live game listener (stream an in-progress game, update the curve in real time)

See [docs/RUNBOOK.md](docs/RUNBOOK.md) to run the pipeline and
[docs/MAINTENANCE.md](docs/MAINTENANCE.md) to keep it healthy.

## Down the road

**Next up: a live game listener.** Poll an in-progress game from the NBA's live
play-by-play feed, track the clock and score, and update the win-probability curve
in real time - turning the game-replay view into a live scoreboard. The
`MatchupPredictor` is already built to be called once per update; the listener is
the piece that feeds it live state.

### Shipped: player-aware team strength

Team Elo is a lagging, team-level signal - it can't react to a mid-season trade
until results pile up. So the model now also sees each team's **current roster**:

1. **On-court lineups** are reconstructed from box-score starters + play-by-play
   substitutions (`build_lineups.py`), validated to ~0.99 correlation against
   official box-score minutes.
2. **Learned player value (RAPM)** - a ridge regression of stint point-margin on
   which ten players are on the floor (`build_rapm.py`), so a defender who never
   scores still earns credit. SGA and Giannis top the league, as they should.
3. **Two roster-strength features** feed the model: the learned RAPM gap and a
   box-score Game Score gap (they're complementary - RAPM is low-bias/noisy, Game
   Score the reverse). Built from who actually appeared, so a traded player's value
   follows them automatically. Holdout BSS: **0.387 (Elo only) -> 0.413**.

Each step was gated on evidence: a near-free box-score proxy validated the
hypothesis before the expensive RAPM compute. See
[MAINTENANCE.md](docs/MAINTENANCE.md) for the metrics.

A few further directions, now that this works:

- **Validate RAPM** against the NBA's official player-tracking metrics (2013-14+),
  the same convergent-validity check used for Elo. A sanity test, not a feature.
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
├── docs/          # RUNBOOK.md (pipeline commands) and MAINTENANCE.md (long-term upkeep)
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
