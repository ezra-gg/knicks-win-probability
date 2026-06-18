
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select seconds_remaining
from "nba"."main"."features"
where seconds_remaining is null



  
  
      
    ) dbt_internal_test