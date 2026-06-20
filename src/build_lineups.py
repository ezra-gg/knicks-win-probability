"""
Phase 1 (player-aware strength) - reconstruct on-court lineups per game.

Lineup tracking is sequential (walk substitutions in order, maintaining a running
five-man set per team), so like the Elo builder it lives in Python rather than
SQL and writes a table dbt builds on. Inputs: each team's five starters from the
box score, and the substitution events from the play-by-play. Output: one row per
"stint" - a span over which the full ten-man lineup is unchanged.

Substitutions name the outgoing player by id but the incoming player only in free
text ("SUB: <in> FOR <out>"), so we resolve the incoming name against the game's
box-score roster here before the reconstruction loop consumes clean ids.
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path

import duckdb
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("build_lineups")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "nba.duckdb"
DEFAULT_OUT_PATH = PROJECT_ROOT / "data" / "lineups.parquet"

# "SUB: <incoming> FOR <outgoing>" - capture the incoming player's name.
SUB_RE = re.compile(r"SUB:\s*(.+?)\s+FOR\s+", re.IGNORECASE)


def _last_name(name_i: str) -> str:
    """Box-score 'J. Murray' -> 'Murray'; 'M. Porter Jr.' -> 'Porter Jr.'.

    Substitution descriptions use the surname form, so we strip the leading
    'F.' initial to match. Names without an initial pass through unchanged.
    """
    parts = str(name_i).split(". ", 1)
    return parts[1] if len(parts) == 2 else parts[0]


def load_rosters(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, str]]:
    """Per game: surname -> person_id, the resolver for incoming substitutes.

    Built from two sources so a name resolves whether or not the player scored:
    the box-score roster ('J. Murray' -> 'Murray') and the play-by-play
    player_name (already the surname, in the exact form the SUB text uses). All
    ids are cast to text so they compare equal to the play-by-play side, which
    stores person_id as an integer. Surname collisions within a game are dropped
    and logged, so the substitution stays unresolved rather than picking wrong.
    """
    
    df = con.execute("""
        select game_id, cast(person_id as varchar) as person_id, player_name
        from stg_boxscores
        union all
        select game_id, cast(person_id as varchar) as person_id, player_name
        from stg_play_by_play
        where person_id is not null and player_name is not null
          and game_id in (select distinct game_id from stg_boxscores)
    """).df()

    # The SUB text uses a bare surname when it is unique in the game ("Robinson")
    # and an initialed form when two players share one ("D. Johnson"). So we key
    # on both: the full 'I. Surname' form (always unambiguous) plus the bare
    # surname (kept only when it maps to a single player). The full form wins.
    rosters: dict[str, dict[str, str]] = {}
    collisions = 0
    for game_id, grp in df.groupby("game_id"):
        full: dict[str, str] = {}
        surname: dict[str, str | None] = {}
        for r in grp.itertuples(index=False):
            name = str(r.player_name)
            if ". " in name:                       # 'D. Johnson' -> distinct key
                full.setdefault(name, r.person_id)
            sn = _last_name(name)
            if sn in surname and surname[sn] not in (None, r.person_id):
                surname[sn] = None                 # ambiguous surname
                collisions += 1
            else:
                surname.setdefault(sn, r.person_id)
        resolver = {k: v for k, v in surname.items() if v is not None}
        resolver.update(full)
        rosters[game_id] = resolver
    if collisions:
        log.info("Ambiguous surnames (resolved via initial form where possible): %d", collisions)
    return rosters


def load_starters(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, list[str]]]:
    """Per game: team -> its five starters' person_ids."""
    df = con.execute("""
        select game_id, team, person_id
        from stg_boxscores
        where is_starter
        order by game_id, team
    """).df()
    starters: dict[str, dict[str, list[str]]] = {}
    for (game_id, team), grp in df.groupby(["game_id", "team"]):
        starters.setdefault(game_id, {})[team] = list(grp["person_id"])
    return starters


def load_subs(con: duckdb.DuckDBPyConnection,
              rosters: dict[str, dict[str, str]]) -> dict[str, list[dict]]:
    """Per game: substitutions in action order, with both players as person_ids.

    player_out comes straight from the event's person_id; player_in is parsed
    from the description and resolved against the game's roster. Unresolved
    incoming players are dropped and counted.
    """
    df = con.execute("""
        select s.game_id, s.action_number, s.period, s.team_tricode as team,
               cast(s.person_id as varchar) as player_out, s.description
        from stg_play_by_play s
        where s.action_type = 'Substitution'
          and s.game_id in (select distinct game_id from stg_boxscores)
        order by s.game_id, s.action_number
    """).df()

    subs: dict[str, list[dict]] = {}
    unresolved = 0
    for r in df.itertuples(index=False):
        match = SUB_RE.search(str(r.description))
        roster = rosters.get(r.game_id, {})
        player_in = roster.get(match.group(1).strip()) if match else None
        if player_in is None:
            unresolved += 1
            continue
        subs.setdefault(r.game_id, []).append({
            "action_number": int(r.action_number),
            "period": int(r.period),
            "team": r.team,
            "player_out": r.player_out,
            "player_in": player_in,
        })
    if unresolved:
        log.info("Substitutions with an unresolved incoming player: %d", unresolved)
    return subs


def period_bounds(con: duckdb.DuckDBPyConnection) -> dict[str, dict[int, tuple[int, int]]]:
    """Per game and period: (first, last) action_number, so each period's stints
    span its real start and end. Anchoring resets the lineup at each boundary."""
    df = con.execute("""
        select game_id, period,
               min(action_number) as first, max(action_number) as last
        from stg_play_by_play
        where game_id in (select distinct game_id from stg_boxscores)
        group by game_id, period
    """).df()
    bounds: dict[str, dict[int, tuple[int, int]]] = {}
    for r in df.itertuples(index=False):
        bounds.setdefault(r.game_id, {})[int(r.period)] = (int(r.first), int(r.last))
    return bounds


def load_actor_events(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Non-substitution events that name a player (a shot, rebound, foul, ...).

    These mark a player as present on the floor. Used to derive who started each
    period: a player active before being subbed in must have been on court at the
    period's tip.
    """
    return con.execute("""
        select game_id, period, action_number, team_tricode as team,
               cast(person_id as varchar) as person_id
        from stg_play_by_play
        where action_type <> 'Substitution'
          and person_id is not null and person_id <> '0'
          and team_tricode is not null
          and game_id in (select distinct game_id from stg_boxscores)
    """).df()


def derive_period_starts(
    actor_df: pd.DataFrame, subs: dict[str, list[dict]],
) -> dict[str, dict[int, dict[str, set[str]]]]:
    """Who was on court at the start of each period, inferred from the events.

    A player started a period if their earliest involvement in it - a stat event
    or being subbed OUT - comes before they were ever subbed IN that period (or
    they were never subbed in). This re-anchors the lineup each period so subs
    made during the break, which the event stream never records, can't drift it.
    """
    # earliest action where each (game, period, team, player) is "present", and
    # the earliest action where they were subbed in.
    present: dict[tuple, int] = {}
    subbed_in: dict[tuple, int] = {}

    for r in actor_df.itertuples(index=False):
        key = (r.game_id, int(r.period), r.team, r.person_id)
        present[key] = min(present.get(key, r.action_number), r.action_number)

    for game_id, game_subs in subs.items():
        for s in game_subs:
            out_key = (game_id, s["period"], s["team"], s["player_out"])
            in_key = (game_id, s["period"], s["team"], s["player_in"])
            present[out_key] = min(present.get(out_key, s["action_number"]), s["action_number"])
            subbed_in[in_key] = min(subbed_in.get(in_key, s["action_number"]), s["action_number"])

    starts: dict[str, dict[int, dict[str, set[str]]]] = {}
    for key, first_present in present.items():
        game_id, period, team, player = key
        first_in = subbed_in.get(key)
        if first_in is None or first_present < first_in:
            starts.setdefault(game_id, {}).setdefault(period, {}).setdefault(team, set()).add(player)
    return starts


def reconstruct_stints(period_starts: dict[int, dict[str, set[str]]], subs: list[dict],
                       bounds: dict[int, tuple[int, int]]) -> list[dict]:
    """Walk each period, emitting a stint each time the ten-man set changes.

    A stint is a span [start_action, end_action) over which both teams' five
    on-court players are constant. Each period is re-anchored to its own starting
    five (so a substitution made during the break can't drift the running set),
    then that period's subs are applied in order. Returns dicts with
    start_action, end_action, and lineups {team: (5 ids)}.
    """
    stints = []
    for period in sorted(bounds):
        # Re-anchor: start the period from who actually took the floor for it.
        on_court = {team: set(players) for team, players in period_starts.get(period, {}).items()}
        first_action, last_action = bounds[period]

        def snapshot(start: int, end: int, on_court=on_court) -> dict:
            # Freeze the live sets into sorted tuples so each stint is a stable
            # record, not a reference that keeps mutating as the walk continues.
            return {
                "start_action": start,
                "end_action": end,
                "lineups": {team: tuple(sorted(players)) for team, players in on_court.items()},
            }

        start = first_action
        for sub in subs:
            if sub["period"] != period:
                continue
            stints.append(snapshot(start, sub["action_number"]))
            on_court.setdefault(sub["team"], set()).discard(sub["player_out"])
            on_court.setdefault(sub["team"], set()).add(sub["player_in"])
            start = sub["action_number"]
        stints.append(snapshot(start, last_action))
    return stints


def build_lineups(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    rosters = load_rosters(con)
    starters = load_starters(con)
    subs = load_subs(con, rosters)
    bounds = period_bounds(con)
    period_starts = derive_period_starts(load_actor_events(con), subs)
    log.info("Reconstructing lineups for %d games.", len(starters))

    rows = []
    for game_id, team_starters in starters.items():
        game_starts = period_starts.get(game_id, {})
        # Period 1 is anchored to the box-score starters (the most reliable
        # source); later periods use the event-derived starting fives.
        game_starts[1] = {team: set(ids) for team, ids in team_starters.items()}
        stints = reconstruct_stints(game_starts, subs.get(game_id, []), bounds.get(game_id, {}))
        for i, stint in enumerate(stints):
            for team, lineup in stint["lineups"].items():
                rows.append({
                    "game_id": game_id,
                    "stint": i,
                    "start_action": stint["start_action"],
                    "end_action": stint["end_action"],
                    "team": team,
                    "lineup": "-".join(sorted(lineup)),  # stable 5-man id key
                })
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconstruct on-court lineups per game.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    args = parser.parse_args()

    if not args.db_path.exists():
        raise FileNotFoundError(f"{args.db_path} not found. Run scripts/load.sh first.")

    con = duckdb.connect(str(args.db_path), read_only=True)
    try:
        lineups = build_lineups(con)
    finally:
        con.close()

    log.info("Writing %d stint-rows to %s...", len(lineups), args.out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    lineups.to_parquet(args.out, index=False)

    con_rw = duckdb.connect(str(args.db_path))
    try:
        con_rw.register("lineups_df", lineups)
        con_rw.execute("CREATE OR REPLACE TABLE lineups AS SELECT * FROM lineups_df")
        log.info("Wrote lineups table to %s.", args.db_path)
    finally:
        con_rw.close()
    log.info("Done.")


if __name__ == "__main__":
    main()
