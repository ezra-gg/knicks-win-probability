-- One row per (game, player) from the traditional box score. The API pads each
-- team's list with inactive/empty slots that carry a personId but no name; we
-- drop those by requiring a name. The five starters per team are the first five
-- real rows the API returns - it lists starters before the bench in every era -
-- captured at ingest as player_order. DNPs (named, null minutes) are kept; they
-- simply never appear in a lineup.
with real_players as (
    select * from {{ source('nba', 'boxscores') }}
    where "nameI" is not null
),

ranked as (
    select
        *,
        row_number() over (
            partition by "gameId", "teamTricode" order by player_order
        ) as team_player_rank
    from real_players
)

select
    "gameId"                  as game_id,
    "teamId"                  as team_id,
    "teamTricode"             as team,
    "personId"               as person_id,
    "nameI"                  as player_name,
    team_player_rank <= 5    as is_starter,
    "position"               as position,
    minutes,
    points,
    "reboundsOffensive"      as rebounds_offensive,
    "reboundsDefensive"      as rebounds_defensive,
    "reboundsTotal"          as rebounds_total,
    assists,
    steals,
    blocks,
    turnovers,
    "foulsPersonal"          as fouls,
    "fieldGoalsMade"         as fg_made,
    "fieldGoalsAttempted"    as fg_attempted,
    "threePointersMade"      as fg3_made,
    "threePointersAttempted" as fg3_attempted,
    "freeThrowsMade"         as ft_made,
    "freeThrowsAttempted"    as ft_attempted,
    "plusMinusPoints"        as plus_minus
from ranked
