
  
  create view "nba"."main"."stg_play_by_play__dbt_tmp" as (
    select
    "gameId"       as game_id,
    "actionNumber" as action_number,
    period,
    clock,
    "scoreHome"    as score_home,
    "scoreAway"    as score_away,
    "teamTricode"  as team_tricode,
    "personId"     as person_id,
    "playerName"   as player_name,
    "isFieldGoal"  as is_field_goal,
    "shotResult"   as shot_result,
    "shotDistance" as shot_distance,
    "shotValue"    as shot_value,
    "xLegacy"      as x,
    "yLegacy"      as y,
    "actionType"   as action_type,
    "subType"      as sub_type
from "nba"."main"."play_by_play"
  );
