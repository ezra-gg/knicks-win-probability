
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select is_overtime
from "nba"."main"."features"
where is_overtime is null



  
  
      
    ) dbt_internal_test