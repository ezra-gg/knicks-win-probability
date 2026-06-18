
    
    

with all_values as (

    select
        is_overtime as value_field,
        count(*) as n_records

    from "nba"."main"."features"
    group by is_overtime

)

select *
from all_values
where value_field not in (
    '0','1'
)


