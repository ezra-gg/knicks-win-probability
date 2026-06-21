-- Per game: each team's roster value and the home - away difference, the model
-- feature(s). Built from who *actually appeared* in the box score, so a traded
-- player's value follows them to their new team automatically - this is the
-- whole point, and why a mid-season trade reprices a team the moment the new
-- player shows up in a box score.
--
-- Two values per player are summed in parallel: the learned RAPM (primary) and
-- the box-score Game Score (a correlated, cruder signal kept as a second
-- feature). Left joins so a player missing one metric just contributes 0 to it.
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
        sum(rapm.value) as roster_rapm,
        sum(box.value)  as roster_box
    from appearances a
    inner join games g on a.game_id = g.game_id
    left join {{ ref('stg_player_rapm') }} rapm
        on rapm.season = g.season and rapm.person_id = a.person_id
    left join {{ ref('player_value_seasons') }} box
        on box.season = g.season and box.person_id = a.person_id
    group by a.game_id, a.team
)

select
    g.game_id,
    home.roster_rapm - away.roster_rapm as roster_value_diff,      -- learned (RAPM)
    home.roster_box  - away.roster_box  as roster_value_box_diff   -- box-score (Game Score)
from games g
inner join team_value home on home.game_id = g.game_id and home.team = g.home_abbr
inner join team_value away on away.game_id = g.game_id and away.team = g.away_abbr
