# Data dictionary

| Field | Meaning / unit | Handling |
| --- | --- | --- |
| PLAYER_ID | NBA player identifier | Unique positive integer per season |
| PLAYER_NAME | Source display name | Required; not used as a join key |
| TEAM_ABBREVIATION | API season aggregate team label | Not a team-stint split |
| GP | Games played | Eligibility ≥20 by default |
| MIN | Minutes per game | Eligibility ≥15 by default |
| PTS, AST, REB | Points, assists, rebounds per game | Nonnegative |
| TS_PCT | True shooting, fraction | .60 = 60%; required |
| AST_TO | Assist-to-turnover ratio | Required; capped contribution at 4 |
| NET_RATING | Net rating, per 100 possessions | Required; contextual |
| USG_PCT | Usage, fraction | .25 = 25%; required |
| PIE | Player impact estimate, fraction | Optional; neutral fallback flagged |
| D_FG_PCT | Defended field-goal percentage, fraction | Source context |
| NORMAL_FG_PCT | Reference field-goal percentage, fraction | Source context |
| PCT_PLUSMINUS | Defended minus reference FG%, fraction | Lower is better for this proxy |
| SALARY | Annual USD, provided or estimated | Default is explicitly estimated |
| SALARY_SOURCE | Estimate label or provided source URL | Exported for every player |
| defense_missing, pie_missing | Neutral imputation flags | True means fallback was used |
| efficiency_composite | Weighted efficiency contribution | Maximum 40 |
| role_difficulty | Weighted role/workload proxy contribution | Maximum 35; historical field name |
| versatility | Weighted multi-category contribution | Maximum 25; not position flexibility |
| position_flex | Normalized PIE | Historical name; not measured flexibility |
| production_value | Sum of production components | 0–100 |
| investment_index | Salary/opportunity/recognition denominator | Floor 15 |
| performance_penalty | Multiplicative performance screen | .3, .6, .8, or 1 |
| underrated_score | Production / investment × penalty | Historical name; heuristic value |
| rating | Descriptive score band | Not a validated assessment |
| league_rank, team_rank | Descending score ranks | Ties share minimum rank |
| model_version | v2 or legacy | Legacy changes defense scaling only |

Base exports also retain available TEAM_ID, STL, BLK, TOV and FG_PCT for inspection; these do not enter the current score. Source-only fields should not be mistaken for modeled features.
