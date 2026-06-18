
    
    

with all_values as (

    select
        home_won as value_field,
        count(*) as n_records

    from "nba"."main"."features"
    group by home_won

)

select *
from all_values
where value_field not in (
    '0','1'
)


