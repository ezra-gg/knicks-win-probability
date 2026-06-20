db      := justfile_directory() + "/data/nba.duckdb"
dbt_bin := justfile_directory() + "/.venv/bin/dbt"
py      := justfile_directory() + "/.venv/bin/python"

# List available recipes
default:
    @just --list

# Pass any dbt subcommand through with env and profiles-dir pre-wired.
# Examples:
#   just dbt build
#   just dbt build -s features
#   just dbt test -s assert_shots_fgm_lte_fga
#   just dbt seed
#   just dbt docs generate && just dbt docs serve
dbt *args:
    cd transform && KNICKS_DB_PATH={{db}} DBT_PROFILES_DIR=. {{dbt_bin}} {{args}}

# --- data pipeline ---

# Ingest game index + play-by-play from nba_api (long-running, see warning)
ingest *args:
    ./scripts/ingest.sh {{args}}

# Load raw CSVs into DuckDB
load:
    ./scripts/load.sh

# Rebuild Elo team ratings (writes parquet + DuckDB table)
ratings:
    ./scripts/ratings.sh

# Compare our Elo to Net Rating and SRS benchmarks
compare *args:
    ./scripts/compare.sh {{args}}

# Train the win probability model
train *args:
    {{py}} src/train.py {{args}}

# Win probability for a specific matchup, e.g. `just predict NYK BOS`
predict *args:
    {{py}} src/predict.py {{args}}

# Export the compact serving artifacts the app reads (decoupled from DuckDB)
export:
    {{py}} src/export_serving_data.py

# Launch the Streamlit showcase app
app *args:
    {{py}} -m streamlit run app/streamlit_app.py {{args}}

# --- quality ---

# Run Python unit tests (pytest)
test *args:
    {{py}} -m pytest {{args}}

# Lint Python with ruff
lint *args:
    {{py}} -m ruff check src/ {{args}}

# --- full pipeline ---

# Reload DuckDB from CSVs then run a full dbt build
rebuild: load
    just dbt build

# Rebuild everything WITHOUT pulling new data. Two-phase because the Python Elo
# step sits in the middle of the dbt DAG: it reads int_roster_continuity and
# writes team_ratings, which later models depend on.
#   1. build continuity (+ its upstream) so ratings can read it
#   2. run the Elo ratings (writes the team_ratings table)
#   3. full dbt build of the ratings-dependent models, then train
pipeline: load
    just dbt build -s +int_roster_continuity
    just ratings
    just dbt build
    just train
    just export

# Everything end to end including the data pull. Same command cold or warm:
# ingest is incremental, so a refresh only fetches new games. For an overnight
# run on macOS, wrap it to stay awake and survive a closed terminal:
#   nohup caffeinate -i just full > run.log 2>&1 &
full:
    just ingest
    just pipeline

# Scheduled refresh: rebuild + publish only if the season has new games. Runs
# the cheap freshness check first, then `just full` and a push to main. Wired
# to launchd for a daily cron (see deploy/ for the LaunchAgent).
refresh:
    ./scripts/refresh.sh
