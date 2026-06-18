with

pbp as (
    select * from "nba"."main"."stg_play_by_play"
),

games as (
    select game_id, season from "nba"."main"."stg_games"
),

-- person_id 0 is non-player rows (period starts, timeouts, etc.)
player_events as (
    select
        g.season,
        p.team_tricode  as team,
        p.person_id,
        p.player_name   as player,
        p.game_id,
        p.is_field_goal,
        p.shot_result,
        p.shot_value
    from pbp p
    inner join games g on p.game_id = g.game_id
    where p.person_id is not null
      and p.person_id <> 0
      and p.player_name is not null
),

aggregated as (
    select
        season,
        team,
        person_id,
        any_value(player)                                              as player,
        count(distinct game_id)                                        as games,
        count(*)                                                       as events,
        sum(case when is_field_goal = 1 then 1 else 0 end)            as fga,
        sum(case when shot_result = 'Made' then 1 else 0 end)         as fgm,
        sum(case when shot_result = 'Made' then shot_value else 0 end) as fg_points
    from player_events
    group by season, team, person_id
)

select
    season,
    team,
    person_id,
    player,
    games,
    events,
    fga,
    fgm,
    fg_points,
    -- Share of team's field-goal points this season; the involvement weight
    -- used for roster-continuity math in the player-aware Elo extension.
    fg_points / nullif(sum(fg_points) over (partition by season, team), 0) as point_share
from aggregated
order by season, team, fg_points desc