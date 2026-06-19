select
    game_id,
    game_date,
    season,
    season_type,
    case when season_type = 'Playoffs' then 1 else 0 end as is_playoff,
    home_abbr,
    away_abbr,
    home_pts,
    away_pts,
    home_won
from {{ source('nba', 'games') }}
