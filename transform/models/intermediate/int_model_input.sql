-- The single table train.py consumes: every play-by-play feature row joined to
-- its game's pre-game Elo gap. One SELECT * downstream, no pandas joins.
with

features as (
    select * from {{ ref('features') }}
),

ratings as (
    select game_id, rating_diff from {{ ref('stg_team_ratings') }}
)

select
    f.game_id,
    f.game_date,
    f.season,
    f.period,
    f.seconds_remaining,
    f.score_diff,
    f.is_overtime,
    r.rating_diff,
    f.home_won
from features f
inner join ratings r on f.game_id = r.game_id
