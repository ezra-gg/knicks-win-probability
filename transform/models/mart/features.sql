with

pbp as (
    select * from {{ ref('stg_play_by_play') }}
),

games as (
    select game_id, game_date, season, is_playoff, home_won from {{ ref('stg_games') }}
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
        -- Before the first basket there is no prior score to forward-fill, so
        -- the filled value is null. The game is tied 0-0 at that point, so
        -- coalesce to 0 rather than leaking a null into the model.
        coalesce(f.score_home_filled, 0)
            - coalesce(f.score_away_filled, 0)     as score_diff,
        -- The running totals themselves (not used by the model, which only sees
        -- the differential) so the replay can show the live scoreboard on hover.
        coalesce(f.score_home_filled, 0)           as score_home,
        coalesce(f.score_away_filled, 0)           as score_away,
        case when f.period > 4 then 1 else 0 end   as is_overtime,
        -- Parse PT12M00.00S into seconds left in the game. In regulation that is
        -- this period's clock plus the full quarters after it. In OT it is just
        -- the OT clock (each OT is its own 5-minute period that can end the game);
        -- is_overtime tells the model which regime a small value belongs to.
        case
            when f.period > 4 then
                cast(regexp_extract(f.clock, 'PT(\d+)M', 1) as integer) * 60
                + cast(regexp_extract(f.clock, 'M([\d.]+)S', 1) as double)
            else
                (
                    cast(regexp_extract(f.clock, 'PT(\d+)M', 1) as integer) * 60
                    + cast(regexp_extract(f.clock, 'M([\d.]+)S', 1) as double)
                )
                + (4 - f.period) * 720
        end                                        as seconds_remaining,
        g.is_playoff,
        g.game_date,
        g.season,
        g.home_won
    from filled_scores f
    inner join games g on f.game_id = g.game_id
)

select * from final
