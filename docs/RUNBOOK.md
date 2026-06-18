# Runbook

How to run the pipeline and recover when a stage fails. For the why-it-is-built-this-way
decisions, see the README. For long-term stewardship, see [MAINTENANCE.md](MAINTENANCE.md).

## The pipeline

Five stages, run in order. Each consumes the previous stage's output.

```
ingest  ->  load  ->  ratings  ->  dbt build  ->  train
(nba_api)  (DuckDB)   (Elo)        (features)     (model)
```

| Stage | Command | Produces | Rough time |
| ----- | ------- | -------- | ---------- |
| Ingest | `just ingest` | `data/raw/games.csv`, `data/raw/play_by_play.csv` | ~14h full history, seconds when incremental |
| Load | `just load` | tables in `data/nba.duckdb` | seconds |
| Ratings | `just ratings` | `data/team_ratings.parquet` + `team_ratings` table | seconds |
| Transform | `just dbt build` | staging/intermediate/mart models + tests | ~3s |
| Train | `just train` | `models/win_probability.pkl` | ~50s |

Three intent-based bundles cover the common cases:

```bash
just full          # everything: ingest + load + ratings + dbt build + train
just pipeline      # rebuild WITHOUT pulling data (after a code/feature/param change)
just ingest        # pull data only (e.g. overnight; rebuild later with just pipeline)
```

`just full` is the same command cold or warm: ingest is incremental, so a refresh
only fetches new games and the fast downstream stages rebuild. For an overnight run
on macOS, wrap it to stay awake and survive a closed terminal:

```bash
nohup caffeinate -i just full > run.log 2>&1 &
```

`caffeinate` stays out of the recipe on purpose (it is macOS-only); wrapping keeps
`just full` portable.

Quality gates, run anytime:

```bash
just test          # pytest unit tests (the split's leakage guarantee, etc.)
just lint          # ruff over src/
just dbt test      # dbt data-quality tests on the warehouse tables
just compare       # sanity-check our Elo against Net Rating and SRS
```

## Stage details

### Ingest (`just ingest`)

Pulls the game index and per-game play-by-play from the public NBA stats API.
Defaults to the 2000-01 season through the current one. It is **incremental**:
re-running skips games already on disk, so it is safe to interrupt and resume.

A full historical pull is ~31k games at roughly 1.6s each, so it warns and
estimates the wall time before starting anything over five minutes. Run it
detached and keep the Mac awake:

```bash
nohup ./scripts/ingest.sh > ingest_run.log 2>&1 &
caffeinate -i -w $!      # prevent sleep until that PID exits
```

### Load (`just load`)

Reads the raw CSVs into DuckDB (`data/nba.duckdb`). The CSVs are the source of
truth; DuckDB is a regenerable query layer. The `games` table is complete even
when play-by-play is still downloading, which is why ratings can run early.

### Ratings (`just ratings`)

Computes leakage-safe pre-game Elo and writes it two ways: `team_ratings.parquet`
and a `team_ratings` table inside DuckDB. The DuckDB table is what dbt joins, so
**ratings must run before `dbt build`**. Elo lives in Python because it is a
sequential update loop, not a set transform.

### Transform (`just dbt build`)

Runs the dbt DAG and its tests: staging views over the raw tables, the
`int_model_input` intermediate model (features joined to the pre-game Elo gap),
and the mart tables. `build` runs models and tests together.

### Train (`just train`)

Loads `int_model_input`, makes a three-way time split, fits a logistic baseline
and an XGBoost model, evaluates on the holdout, runs the basketball sanity gate,
and saves the model. The sanity asserts are a hard gate: a model that fails them
halts the run and nothing is saved.

## Common failures and fixes

| Symptom | Cause | Fix |
| ------- | ----- | --- |
| `XGBoostError: libxgboost.dylib could not be loaded ... libomp` | macOS lacks the OpenMP runtime XGBoost needs | `brew install libomp` |
| `Catalog Error: Table with name team_ratings does not exist` during `dbt build` | ran dbt before ratings | run `just ratings` first |
| `Input X contains NaN` in train | a feature has nulls (e.g. score before the first basket) | fix at the source in dbt, not in Python; add a `not_null` test to catch regressions |
| `ModuleNotFoundError` (pyarrow, lxml, xgboost, ...) | venv missing a dep | `./scripts/setup.sh` or `pip install -r requirements.txt` |
| Ingest stalls or times out | nba_api rate-limiting or flaky network | it retries with backoff; if it gives up on a game, just re-run, it resumes |
| dbt cannot find the database | `KNICKS_DB_PATH` unset | use the `just dbt` recipe, which sets it for you |

## Refreshing for a new season

```bash
just full      # pulls only new games, then reloads, re-rates, rebuilds, retrains
```

The train/test split windows slide forward on their own (they are derived from
the data, not hardcoded), so the newest season automatically becomes the holdout.
Nothing to hand-edit. Tunables, if you do want to change any, are all in
`params.yml`.

## Re-running a single dbt model

```bash
just dbt build -s features          # one model + its tests
just dbt build -s +int_model_input  # a model and everything upstream of it
just dbt build -s models/mart       # everything in a folder
```
