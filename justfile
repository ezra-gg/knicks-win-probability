db      := justfile_directory() + "/data/nba.duckdb"
dbt_bin := justfile_directory() + "/.venv/bin/dbt"

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

# Rebuild Elo team ratings (writes to data/team_ratings.parquet)
ratings:
    ./scripts/ratings.sh

# Reload DuckDB from CSVs then run a full dbt build
rebuild: load
    just dbt build
