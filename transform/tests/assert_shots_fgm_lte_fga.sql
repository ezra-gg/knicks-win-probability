-- Return any player-team-season where a player made more shots than they
-- attempted. fgm > fga is physically impossible and indicates a data bug.
select *
from {{ ref('player_team_seasons') }} as pts
where pts.fgm > pts.fga