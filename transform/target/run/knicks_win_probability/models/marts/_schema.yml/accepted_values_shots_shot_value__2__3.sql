
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        shot_value as value_field,
        count(*) as n_records

    from "nba"."main"."shots"
    group by shot_value

)

select *
from all_values
where value_field not in (
    '2','3'
)



  
  
      
    ) dbt_internal_test