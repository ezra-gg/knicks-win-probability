
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select games
from "nba"."main"."player_team_seasons"
where games is null



  
  
      
    ) dbt_internal_test