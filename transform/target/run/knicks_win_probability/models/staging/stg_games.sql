
  
  create view "nba"."main"."stg_games__dbt_tmp" as (
    select
    game_id,
    game_date,
    season,
    home_abbr,
    away_abbr,
    home_pts,
    away_pts,
    home_won
from "nba"."main"."games"
  );
