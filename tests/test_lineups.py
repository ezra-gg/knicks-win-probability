"""Runtime data-alignment gate for the reconstructed lineups.

Unlike the synthetic unit tests, this one reads the built warehouse and asserts
that reconstructed on-court minutes track the official box-score minutes - an
independent check that players are placed on court at the right times. It needs
the pipeline to have run, so it skips (rather than fails) when the DuckDB or the
lineup tables are not present, e.g. on a fresh clone or in CI.
"""

from pathlib import Path

import duckdb
import pytest

from validate_lineups import align_minutes

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "nba.duckdb"
MIN_CORRELATION = 0.95


def _has_rows(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    try:
        return con.execute(f"select count(*) from {table}").fetchone()[0] > 0
    except duckdb.Error:
        return False


@pytest.mark.skipif(not DB_PATH.exists(), reason="no DuckDB - run the pipeline first")
def test_reconstructed_minutes_align_with_official():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        if not (_has_rows(con, "stg_lineups") and _has_rows(con, "stg_boxscores")):
            pytest.skip("lineups/box scores not built yet (run `just lineups`)")
        merged = align_minutes(con)
    finally:
        con.close()

    corr = merged["recon_min"].corr(merged["official_min"])
    assert corr >= MIN_CORRELATION, (
        f"reconstructed vs official minutes correlation {corr:.4f} "
        f"below the {MIN_CORRELATION} floor - lineup reconstruction has drifted"
    )
