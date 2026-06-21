-- One row per stint, shaped for RAPM: the home and away five-man units on the
-- floor, the point margin they produced (home minus away), and the duration.
-- build_rapm.py regresses margin-per-possession on which players were on court.
--
-- Only clean stints are kept - both teams must resolve to exactly five players
-- (a small share drift off five from unresolved within-period substitutions).
with

games as (
    select game_id, season, home_abbr, away_abbr from {{ ref('stg_games') }}
),

-- Running score and a numeric game clock at every action. score_home/away are
-- null except on scoring plays, so forward-fill them to get the score at any
-- action; the regexp pulls seconds-left-in-period out of the PT12M34.00S clock.
scored as (
    select
        game_id,
        action_number,
        -- 0-0 before the first basket (nothing to forward-fill yet), else the
        -- running score; coalesce so opening-tip stints don't carry a null margin.
        coalesce(last_value(score_home ignore nulls) over w, 0) as score_home,
        coalesce(last_value(score_away ignore nulls) over w, 0) as score_away,
        cast(regexp_extract(clock, 'PT(\d+)M', 1) as integer) * 60
            + cast(regexp_extract(clock, 'M([\d.]+)S', 1) as double) as clock_sec
    from {{ ref('stg_play_by_play') }}
    window w as (
        partition by game_id
        order by action_number
        rows between unbounded preceding and current row
    )
),

-- Pivot the per-team stint rows into one row per stint with both lineups,
-- keeping only the stints where each side is a clean five.
stints as (
    select
        l.game_id,
        g.season,
        l.stint,
        l.start_action,
        l.end_action,
        max(case when l.team = g.home_abbr and l.n_players = 5 then l.lineup end) as home_lineup,
        max(case when l.team = g.away_abbr and l.n_players = 5 then l.lineup end) as away_lineup
    from {{ ref('stg_lineups') }} l
    inner join games g on l.game_id = g.game_id
    group by l.game_id, g.season, l.stint, l.start_action, l.end_action
)

select
    s.game_id,
    s.season,
    s.stint,
    s.home_lineup,
    s.away_lineup,
    -- Points the home team out-scored the away team by over the stint.
    (e.score_home - b.score_home) - (e.score_away - b.score_away) as margin,
    -- Seconds elapsed; the clock counts down within a period and stints never
    -- cross a period boundary, so start-minus-end is the elapsed time.
    b.clock_sec - e.clock_sec as duration_seconds
from stints s
inner join scored b on b.game_id = s.game_id and b.action_number = s.start_action
inner join scored e on e.game_id = s.game_id and e.action_number = s.end_action
where s.home_lineup is not null
  and s.away_lineup is not null
  and b.clock_sec - e.clock_sec > 0
