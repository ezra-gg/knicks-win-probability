
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  -- Return any player-team-season where a player made more shots than
-- they attempted. fgm > fga is physically impossible and indicates a data bug.
-- Reference the player_team_seasons model with "nba"."main"."player_team_seasons".
select *
from "nba"."main"."player_team_seasons" as pts
where pts.fgm > pts.fga
  
  
      
    ) dbt_internal_test