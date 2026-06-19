-- Conformed team dimension: one row per tricode that has ever appeared, each
-- mapped to its current (canonical) code and franchise name. Current teams map
-- to themselves; relocated franchises (e.g. SEA) map onto their new code (OKC).
-- This is the single source of truth the app (display names) and the ratings
-- validation (canonicalization) both read, via the serving export.
with current_teams as (
    select tricode, full_name from {{ ref('team_names') }}
),

aliases as (
    -- One row per historical tricode: it folds onto its current code, and
    -- carries the current franchise's name (a relocated team shares today's
    -- name). Driving from franchise_map keeps the grain at the 5 relocations;
    -- the inner join also drops any seed row whose current_tricode is a typo.
    select
        fm.historical_tricode as tricode,
        fm.current_tricode    as canonical_tricode,
        tn.full_name
    from {{ ref('franchise_map') }} as fm
        inner join {{ ref('team_names') }} as tn
            on fm.current_tricode = tn.tricode
),

final as (
    -- Current teams are their own canonical code.
    select
        tricode,
        tricode      as canonical_tricode,
        full_name,
        true         as is_current
    from current_teams

    union all

    -- Historical aliases fold onto the current franchise.
    select
        tricode,
        canonical_tricode,
        full_name,
        false        as is_current
    from aliases
)

select * from final
