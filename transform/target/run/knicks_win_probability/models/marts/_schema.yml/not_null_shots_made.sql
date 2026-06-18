
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select made
from "nba"."main"."shots"
where made is null



  
  
      
    ) dbt_internal_test