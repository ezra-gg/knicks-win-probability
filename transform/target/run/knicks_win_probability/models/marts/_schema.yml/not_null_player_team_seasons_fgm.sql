
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select fgm
from "nba"."main"."player_team_seasons"
where fgm is null



  
  
      
    ) dbt_internal_test