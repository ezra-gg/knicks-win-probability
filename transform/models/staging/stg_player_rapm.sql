-- Per-season learned player value (RAPM), the swap-in replacement for the
-- box-score Game Score proxy. Same (season, person_id, value) contract, so
-- int_game_roster_value consumes it without change.
select
    season,
    cast(person_id as varchar) as person_id,
    value
from {{ source('nba', 'player_rapm') }}
