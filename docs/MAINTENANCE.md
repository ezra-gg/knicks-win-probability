# Maintenance

Keeping the project healthy over time. For how to run it day to day, see
[RUNBOOK.md](RUNBOOK.md).

## Baseline to beat

The current model on the 2024-25 and 2025-26 holdout. Any change to features or
the model should be measured against these:

| Metric | Logistic (baseline) | XGBoost (shipped) |
| ------ | ------------------- | ----------------- |
| Log loss | 0.4740 | 0.4558 |
| Brier | 0.1579 | 0.1525 |
| Brier skill score | 0.366 | 0.388 |

Holdout is 2024-25 and 2025-26, regular season + playoffs (~33k games total).
Broken down by game type on the XGBoost model:

| Slice | BSS |
| ----- | --- |
| Regular season | 0.394 |
| Playoffs | 0.296 |

The playoff gap is expected - higher-variance games between evenly matched teams.
XGBoost early-stops around 162-181 trees. The sanity gate must stay green: tied at
tip-off ~0.56, up 20 with 10s left ~0.997, down 3 with 5s left ~0.089.

## Where configuration lives

All tunables are in **`params.yml`** at the project root, loaded by `src/config.py`.
One file for Elo settings, model features, the split windows, and XGBoost
hyperparameters. Change values there, not in the code.

## Dependencies

`requirements.txt` pins every direct dependency to the version tested against.
Transitive deps are left unpinned for readability. When bumping a version, run
`just test`, `just lint`, and `just dbt build` before committing. XGBoost also
needs the system `libomp` on macOS (`brew install libomp`); that is not a pip
dependency and will not be captured by `requirements.txt`.

## Things that need a human when the league changes

### Franchise relocations (`transform/seeds/franchise_map.csv`)

When a franchise relocates or rebrands, our Elo keeps the old tricode while the
benchmarks use the new one. The map folds historical codes onto current ones
(SEA->OKC, VAN->MEM, NJN->BKN, NOH/NOK->NOP) so all three rating sources share one
key. It is a dbt seed - a plain CSV that is the single source of truth, read both
by `compare_ratings.py` (directly) and by dbt (`just dbt seed`). To handle a new
relocation, add one row to the CSV; no code change. The Charlotte lineage is
deliberately left unmapped, which costs two team-seasons in the comparison.

(For full automation, `nba_api`'s `FranchiseHistory` endpoint exposes former
cities, but relocations happen roughly once every four years, so a one-row CSV
edit is simpler than maintaining a live derivation.)

### Elo hyperparameters (`params.yml`, `elo:`)

- `base_rating: 1500` - the anchor everyone starts at. Arbitrary; only gaps matter.
- `k_factor: 20` - how far one game moves a rating. Matches FiveThirtyEight's NBA
  Elo. Worth tuning once we can measure prediction quality, but changing it shifts
  every rating, so re-run `just compare` afterward to confirm the correlation with
  Net Rating and SRS still holds (~0.95).

## Things that take care of themselves

### Train/test split windows (`params.yml`, `model.n_holdout` / `n_validation`)

These set how many recent seasons go to holdout and validation. The actual
seasons are derived from the data and slide forward as new ones arrive, so this
does **not** need a yearly edit. Only change them for a different window size.

### Tree count (`params.yml`, `model.xgboost.n_estimators`)

`n_estimators` is a ceiling, not a target. Early stopping picks the real count
from the validation curve. If a run ever actually hits the ceiling, raise it - it
means the model was still improving when it was cut off.

## Adding tests

- **dbt (data quality):** add a generic test under `tests:` in the model's
  `_schema.yml`, or a singular test as a `.sql` file in `transform/tests/` that
  returns rows only when something is wrong.
- **Python (logic):** add a `test_*` function under `tests/`. pytest discovers
  anything matching that prefix.

Both run locally via `just test` / `just dbt test`.

## CI

Every pull request runs two checks (`.github/workflows/ci.yml`):

- **lint** - `ruff check src/`
- **dbt-parse** - validates the dbt project (refs, YAML, Jinja) without touching data

These are required to merge. They are fast because neither needs the database. If
you add a stage that should gate merges (for example running `pytest`), add it as a
new job there.

## Data quality belongs in dbt

When a data problem surfaces in Python (a NaN, an impossible value), fix it in the
dbt layer and add a test, not in the consumer. One fix in `features.sql` protects
every downstream reader; a patch in `train.py` protects only `train.py`. The
tip-off `score_diff` coalesce is the worked example of this.
