select
    game_id,
    game_date,
    season,
    home_abbr,
    away_abbr,
    home_rating_pre,
    away_rating_pre,
    rating_diff
from {{ source('nba', 'team_ratings') }}
