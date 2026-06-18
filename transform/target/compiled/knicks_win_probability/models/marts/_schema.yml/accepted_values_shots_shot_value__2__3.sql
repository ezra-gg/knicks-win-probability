
    
    

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


