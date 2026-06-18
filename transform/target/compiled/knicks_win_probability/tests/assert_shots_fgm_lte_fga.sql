-- Return any player-team-season where a player made more shots than
-- they attempted. fgm > fga is physically impossible and indicates a data bug.
-- Reference the player_team_seasons model with "nba"."main"."player_team_seasons".
select *
from "nba"."main"."player_team_seasons" as pts
where pts.fgm > pts.fga