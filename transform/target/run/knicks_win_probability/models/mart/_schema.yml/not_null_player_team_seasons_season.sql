
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select season
from "nba"."main"."player_team_seasons"
where season is null



  
  
      
    ) dbt_internal_test