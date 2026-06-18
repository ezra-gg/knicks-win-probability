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

## Quickstart

Requires Python 3.12+.

```bash
# 1. Set up the virtual environment and install dependencies
./scripts/setup.sh

# 2. Pull data (game index + play-by-play) through the current season
./scripts/ingest.sh --start-season 2023-24

# 3. Load the raw CSVs into DuckDB
./scripts/load.sh
```

Re-running `ingest.sh` is incremental. It skips games already on disk and only
fetches what's new, so it's safe to interrupt and resume.

## Roadmap

- [x] Data ingestion (game index + play-by-play)
- [x] Local DuckDB storage
- [ ] Feature engineering
- [ ] Model training and calibration
- [ ] Streamlit app

## Tech stack

| Layer           | Tool           |
| --------------- | -------------- |
| Data source     | `nba_api`      |
| Storage         | `DuckDB`       |
| Data processing | `pandas`       |
| Modeling        | `scikit-learn` |
| App             | `Streamlit`    |

## Project layout

```
knicks-win-probability/
├── scripts/       # setup and run wrappers (setup.sh, ingest.sh, load.sh)
├── src/           # ingestion, storage, model code
├── data/          # raw CSVs and the DuckDB database (gitignored)
├── notebooks/     # exploratory analysis
├── app/           # Streamlit dashboard
└── models/        # trained model artifacts
```

## Notes

`nba_api` is an unofficial client for stats.nba.com. This project isn't
affiliated with or endorsed by the NBA, and is meant for personal and
educational use.
