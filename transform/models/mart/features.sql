with

pbp as (
    select * from {{ ref('stg_play_by_play') }}
),

games as (
    select game_id, home_won from {{ ref('stg_games') }}
),

filled_scores as (
    select
        game_id,
        action_number,
        period,
        clock,
        last_value(score_home ignore nulls) over(
            partition by game_id
            order by action_number
            rows between unbounded preceding and current row
        )  as score_home_filled,
        last_value(score_away ignore nulls) over(
            partition by game_id
            order by action_number
            rows between unbounded preceding and current row
        ) as score_away_filled
    from pbp
),

final as (
    select
        f.game_id,
        f.action_number,
        f.period,
        f.score_home_filled - f.score_away_filled  as score_diff,
        case when f.period > 4 then 1 else 0 end   as is_overtime,
        -- Parse PT12M00.00S -> total regulation seconds remaining.
        -- OT plays have no meaningful "time left" in the model, so 0.
        case
            when f.period > 4 then 0.0
            else
                (
                    cast(regexp_extract(f.clock, 'PT(\d+)M', 1) as integer) * 60
                    + cast(regexp_extract(f.clock, 'M([\d.]+)S', 1) as double)
                )
                + (4 - f.period) * 720
        end                                        as seconds_remaining,
        g.home_won
    from filled_scores f
    inner join games g on f.game_id = g.game_id
)

select * from final
