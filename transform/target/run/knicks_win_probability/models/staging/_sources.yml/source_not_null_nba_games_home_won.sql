
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select home_won
from "nba"."main"."games"
where home_won is null



  
  
      
    ) dbt_internal_test