-- Per game: each team's roster value (sum of its appearing players' season
-- value) and the home - away difference, the model feature. Built from who
-- *actually appeared* in the box score, so a traded player's value follows them
-- to their new team automatically - this is the whole point of the feature, and
-- why a mid-season trade reprices a team the moment it shows up in a box score.
with

games as (
    select game_id, season, home_abbr, away_abbr from {{ ref('stg_games') }}
),

-- Players who logged minutes for a team in a game (DNPs have null minutes).
appearances as (
    select game_id, team, person_id
    from {{ ref('stg_boxscores') }}
    where minutes is not null and minutes <> ''
),

team_value as (
    select
        a.game_id,
        a.team,
        sum(pv.value) as roster_value
    from appearances a
    inner join games g on a.game_id = g.game_id
    inner join {{ ref('player_value_seasons') }} pv
        on pv.season = g.season and pv.person_id = a.person_id
    group by a.game_id, a.team
)

select
    g.game_id,
    home.roster_value                       as home_roster_value,
    away.roster_value                       as away_roster_value,
    home.roster_value - away.roster_value   as roster_value_diff
from games g
inner join team_value home on home.game_id = g.game_id and home.team = g.home_abbr
inner join team_value away on away.game_id = g.game_id and away.team = g.away_abbr
