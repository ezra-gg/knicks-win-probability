
    
    

with all_values as (

    select
        made as value_field,
        count(*) as n_records

    from "nba"."main"."shots"
    group by made

)

select *
from all_values
where value_field not in (
    '0','1'
)


