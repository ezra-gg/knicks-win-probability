
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select period
from "nba"."main"."features"
where period is null



  
  
      
    ) dbt_internal_test