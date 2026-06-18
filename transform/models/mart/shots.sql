with

pbp as (
    select * from {{ ref('stg_play_by_play') }}
),

games as (
    select game_id, season, game_date from {{ ref('stg_games') }}
),

shots as (
    select
        p.game_id,
        p.action_number,
        p.period,
        p.team_tricode                             as team,
        p.person_id,
        p.player_name                              as player,
        p.shot_distance,
        p.shot_value,
        p.shot_result,
        p.x,
        p.y,
        p.action_type,
        p.sub_type,
        case when p.shot_result = 'Made' then 1 else 0 end as made,
        -- Seconds remaining in regulation (OT plays collapse to 0)
        case
            when p.period > 4 then 0.0
            else
                (
                    cast(regexp_extract(p.clock, 'PT(\d+)M', 1) as integer) * 60
                    + cast(regexp_extract(p.clock, 'M([\d.]+)S', 1) as double)
                )
                + (4 - p.period) * 720
        end                                        as seconds_remaining
    from pbp p
    where p.is_field_goal = 1
      and p.player_name is not null
)

select
    s.*,
    g.season,
    g.game_date
from shots s
inner join games g on s.game_id = g.game_id
order by s.game_id, s.action_number
