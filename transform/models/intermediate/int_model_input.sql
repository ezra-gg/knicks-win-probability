-- The single table train.py consumes: every play-by-play feature row joined to
-- its game's pre-game Elo gap. One SELECT * downstream, no pandas joins.
with

features as (
    select * from {{ ref('features') }}
),

ratings as (
    select game_id, rating_diff from {{ ref('stg_team_ratings') }}
),

roster as (
    select game_id, roster_value_diff, roster_value_box_diff from {{ ref('int_game_roster_value') }}
)

select
    f.game_id,
    f.action_number,
    f.game_date,
    f.season,
    f.period,
    f.seconds_remaining,
    f.score_diff,
    f.score_home,
    f.score_away,
    f.is_overtime,
    f.is_playoff,
    r.rating_diff,
    -- 0 (neutral) for the rare game without a usable box score - the left join
    -- keeps every training row, and 0 means "roster gap unknown, assume even".
    -- Also keeps the logistic baseline happy: it can't accept NaN like XGBoost.
    coalesce(rv.roster_value_diff, 0)     as roster_value_diff,
    coalesce(rv.roster_value_box_diff, 0) as roster_value_box_diff,
    f.home_won
from features f
inner join ratings r on f.game_id = r.game_id
left join roster rv on f.game_id = rv.game_id
