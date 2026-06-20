-- On-court five-man stints per game (one row per team per stint). n_players is
-- exposed so downstream possession/RAPM models can keep only clean five-man
-- stints; a handful drift off five from within-period substitutions whose
-- incoming player could not be resolved, or a player who logged no box-score
-- event in a period.
select
    game_id,
    stint,
    start_action,
    end_action,
    team,
    lineup,
    len(string_split(lineup, '-')) as n_players
from {{ source('nba', 'lineups') }}
