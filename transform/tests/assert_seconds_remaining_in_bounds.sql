-- Catch clock parsing bugs. Regulation runs 0-2880s (4 × 12min); OT plays carry
-- their own period clock (0-300s), well inside the bound. Any row outside
-- [0, 2880] is a parse error.
select game_id, action_number, period, seconds_remaining
from {{ ref('features') }}
where seconds_remaining < 0
   or seconds_remaining > 2880
