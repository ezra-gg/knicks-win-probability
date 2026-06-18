# 🏀 Knicks Win Probability

A win-probability model trained on historical NBA play-by-play data, with an interactive Streamlit app 
that lets you scrub through any game and watch the live probability curve.
Knicks will always steal the spotlight though.

> Ezra's first just for fun project

## Status

🚧 In active development.

- [x] Phase 0 - Project scaffold & environment
- [ ] Phase 1 - Data ingestion (`nba_api` to local CSVs)
- [ ] Phase 2 - Feature engineering
- [ ] Phase 3 - Model training & calibration
- [ ] Phase 4 - Streamlit app
- [ ] Phase 5 - Polish & ship

## Tech stack

| Layer            | Tool            |
| ---------------- | --------------- |
| Data source      | `nba_api`       |
| Data processing  | `pandas`        |
| Modeling         | `scikit-learn`  |
| App              | `Streamlit`     |

## Setup

```bash
# Create and activate a virtual environment (Python 3.12+)
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Project structure

```
knicks-win-probability/
├── data/raw/      # play-by-play data pulled from nba_api (gitignored)
├── notebooks/     # exploratory analysis
├── src/           # ingestion, features, model code
├── app/           # Streamlit dashboard
├── models/        # trained model artifacts
└── requirements.txt
```
