-- Roster continuity per team per season entered: the fraction of last season's
-- field-goal production that returned. 1.0 = the whole scoring core came back,
-- 0.0 = an entirely new roster. Consumed by the Elo builder to regress a team's
-- rating toward the mean between seasons (more turnover -> bigger regression).
--
-- Scoring is the only player-value signal we have (no minutes or defense), so
-- this is an offense-weighted proxy. Reuses point_share from player_team_seasons.
with

pts as (
    select
        team,
        person_id,
        point_share,
        cast(left(season, 4) as integer) as season_start
    from {{ ref('player_team_seasons') }}
),

-- Each prior-season player, flagged for whether they returned to the same team
-- the next season.
returns as (
    select
        prev.season_start + 1                                   as season_start,  -- season entered
        prev.team,
        prev.point_share,
        case when cur.person_id is not null then 1 else 0 end   as returned
    from pts prev
    left join pts cur
        on cur.team = prev.team
       and cur.person_id = prev.person_id
       and cur.season_start = prev.season_start + 1
)

select
    team,
    season_start,
    sum(point_share * returned) as continuity
from returns
group by team, season_start
