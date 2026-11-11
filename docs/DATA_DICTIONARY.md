# Data dictionary

## Research edition exports (model v2)

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

## BigQuery table: player_scores (formula v2.1)

Table `nba_underrated_score.player_scores`, written by the live loader. One row per player per season; a refresh replaces only the loaded season's rows. Component scores are on a 0–100 percentile scale among players scored that season.

| Field | Meaning / unit | Handling |
| --- | --- | --- |
| SEASON | Season label, `YYYY-YY` | Rows for other seasons are kept on reload |
| PLAYER_ID | NBA player identifier | One row per player per season |
| PLAYER_NAME | Source display name | Join key for optional salary and votes files |
| TEAM_ABBREVIATION | Current team label | Used for team logos and team views |
| GP | Games played | Compared with `gp_gate` |
| MIN | Minutes per game | Scored at 5+; qualified at 15+ |
| PTS, REB, AST | Points, rebounds, assists per game | Feed skill diversity |
| TS_PCT | True shooting, fraction | Efficiency input and penalty screen |
| NET_RATING | Net rating per 100 possessions | Penalty screen |
| USG_PCT | Usage, fraction | Workload and usage cost |
| SALARY | Annual USD | Estimated unless a salary file is supplied |
| efficiency | Efficiency component | 35% of production value |
| role_difficulty | Role difficulty component | 30% of production value |
| versatility | Versatility component | 35% of production value |
| production_value | Production Value (PV) | 0–100; qualifying gate at 50 |
| financial | Financial cost component | 40% of investment index |
| usage_cost | Usage cost component | 35% of investment index |
| recognition | Recognition component | 25% of investment index |
| investment_index | Investment Index (RI) | Floored at 5 in the score |
| penalty_multiplier | Performance penalty | .30, .60, .80, or 1.00 |
| underrated_score | (PV x penalty) / max(RI, 5) | Rounded to 3 decimals |
| rating | Tier label | Seriously Underrated, Quietly Valuable, Fairly Rated, Properly Rated |
| qualified | Passes all three gates | Boolean; defines the ranked cohort |
| gp_gate | Games-played gate used in this load | 30 scaled to the season completed |
| league_rank | Rank by score among all scored players | 1 = highest |
| formula_version | Scoring version | `v2.1` |
| approximations | Approximations used in this load | Semicolon-separated text |
| loaded_at | Load timestamp, UTC | Set by the loader |
