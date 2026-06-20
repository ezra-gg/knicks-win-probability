-- Interim per-player season value from the box score: one number summarizing a
-- player's all-around production, averaged per game. This is the placeholder the
-- roster-value feature consumes; a learned RAPM value swaps in behind the same
-- (season, person_id, value) contract later, with no downstream change.
--
-- Value is team-agnostic (a player's skill, not a team's) - the roster-value
-- model attributes it to whichever team the player actually appeared for.
with

boxscores as (
    select * from {{ ref('stg_boxscores') }}
),

games as (
    select game_id, season from {{ ref('stg_games') }}
),

-- Only games the player actually appeared in (DNPs have null minutes).
per_player_game as (
    select
        g.season,
        b.person_id,
        b.player_name,
        b.points,
        b.fg_made,
        b.fg_attempted,
        b.ft_made,
        b.ft_attempted,
        b.rebounds_offensive,
        b.rebounds_defensive,
        b.assists,
        b.steals,
        b.blocks,
        b.turnovers,
        b.fouls
    from boxscores b
    inner join games g on b.game_id = g.game_id
    where b.minutes is not null and b.minutes <> ''
),

season_totals as (
    select
        season,
        person_id,
        any_value(player_name)      as player,
        count(*)                    as games,
        sum(points)                 as pts,
        sum(fg_made)                as fgm,
        sum(fg_attempted)           as fga,
        sum(ft_made)                as ftm,
        sum(ft_attempted)           as fta,
        sum(rebounds_offensive)     as orb,
        sum(rebounds_defensive)     as drb,
        sum(assists)                as ast,
        sum(steals)                 as stl,
        sum(blocks)                 as blk,
        sum(turnovers)              as tov,
        sum(fouls)                  as pf
    from per_player_game
    group by season, person_id
)

select
    season,
    person_id,
    player,
    games,
    -- Average Game Score per game (Hollinger's transparent one-number box
    -- summary). This is a near-free proxy whose only job is to gate the
    -- expensive RAPM build: if roster value built on it lifts the model, RAPM is
    -- justified; if not, we've saved the regression compute. The exact weights
    -- barely matter for that purpose - it just needs to be directionally right.
    (
        pts
        + 0.4 * fgm
        - 0.7 * fga
        - 0.4 * (fta - ftm)
        + 0.7 * orb
        + 0.3 * drb
        + stl
        + 0.7 * ast
        + 0.7 * blk
        - 0.4 * pf
        - tov
    ) / games as value
from season_totals
order by season, value desc
