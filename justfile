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

# End to end: load, rebuild Elo, build + test dbt models, train the model
pipeline: load ratings
    just dbt build
    just train
