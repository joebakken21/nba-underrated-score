# Methodology and model card

This document covers two models:

- **Formula v2.1 (live, 2026–27):** the production model behind the BigQuery table and the live dashboard, built by [`pipelines/11-11-2026-nba-underrated-score-loader-spyder.py`](../pipelines/11-11-2026-nba-underrated-score-loader-spyder.py).
- **Model v2 (research edition, 2025–26):** the reproducible package in `nba_value/`, used for the sensitivity case study. It is documented from [Intended use](#intended-use) onward.

## Formula v2.1 (live pipeline)

### Score

```text
Underrated Score = (Production Value x Performance Penalty) / max(Investment Index, 5)
```

Production Value (PV) and the Investment Index (RI) are each on a 0–100 scale. The floor of 5 on RI prevents near-zero denominators from producing extreme scores. Every component below is scaled 0–100 by percentile among scored players (5+ minutes per game); missing values land at 50.

### Production Value: what a player gives

| Component | Weight in PV | Built from |
| --- | ---: | --- |
| Efficiency | 35% | 0.34 true shooting + 0.23 playmaking (assist % and assist-to-turnover) + 0.43 on/off net rating |
| Role Difficulty | 30% | 0.40 defensive versatility + 0.33 workload (minutes x usage) + 0.27 lineup strength (carry tax) |
| Versatility | 35% | 0.34 positional flexibility + 0.43 two-way impact + 0.23 skill diversity |

- **Defensive versatility:** opponent field-goal percentage versus expected (70%) and contested-shot volume (30%).
- **Carry tax:** a lower team net rating with the player off the floor earns more credit.
- **Two-way impact:** on-court offensive rating above league average plus defensive rating below league average.
- **Skill diversity:** normalized entropy of points, rebounds, assists, steals, and blocks, each scaled to the league average.

### Investment Index: what a player costs

| Component | Weight in RI | Built from |
| --- | ---: | --- |
| Financial | 40% | 0.65 salary as a share of the max-eligible salary + 0.35 salary per unit of production |
| Usage | 35% | 0.40 usage rate + 0.33 minutes per game + 0.27 touches |
| Recognition | 25% | 0.40 All-Star votes + 0.60 awards, with a linear five-season decay |

Award credit uses the last five completed seasons at weights of 1.0, 0.8, 0.6, 0.4, and 0.2. Award values range from 10 (MVP) to 1 (All-Rookie Team).

### Performance penalty

| Condition (checked in order) | Multiplier |
| --- | ---: |
| Net rating below −10, or true shooting below 45% | 0.30 |
| Net rating below −5 | 0.60 |
| Net rating below 0 and true shooting below 52% | 0.80 |
| Otherwise | 1.00 |

### Qualifying gates

A player is **qualified** when all three hold:

1. **Games played:** 30 over a full season, scaled to the share of the season completed. The gate is `ceil(30 x team games played / 82)`, with a minimum of 1. At the November 11, 2026 load the gate was 5 games.
2. **Minutes:** 15 or more per game.
3. **Production Value:** 50 or more.

All players with 5+ minutes per game are scored and stored; the `qualified` flag separates the ranked cohort.

### Tiers

| Tier | Score |
| --- | --- |
| Seriously Underrated | 2.0 and above |
| Quietly Valuable | 1.5 to 2.0 |
| Fairly Rated | 1.0 to 1.5 |
| Properly Rated | below 1.0 |

### Data sources

All statistics come from the NBA Stats API through `nba_api`: `LeagueDashPlayerStats` (Base and Advanced), `LeagueDashPtDefend`, `LeagueDashPtStats` (Possessions), `LeagueDashTeamStats`, `PlayerIndex`, `TeamPlayerOnOffSummary`, and `PlayerAwards`. Salaries and All-Star votes can be supplied as CSV files; otherwise they are estimated.

### Approximations

The NBA Stats API does not expose every input the formula calls for. Each loaded row records the approximations used in its `approximations` column:

- **Defensive versatility** uses opponent field-goal percentage versus expected, in place of matchup-by-position data.
- **Two-way impact** uses on-court offensive and defensive rating versus league average, in place of OBPM and DBPM.
- **Positional flexibility** uses the roster position listing (G, G-F, F-C), in place of minutes by position.
- **Lineup strength** uses the team's net rating with the player off the floor.
- **Salary** is estimated from minutes and scoring ($1.5M to $35M) when no salary file is supplied, and the max-eligible salary uses one league-wide tier.
- **All-Star votes** use decayed All-Star selections when no votes file is supplied.

### Storage and refresh

The loader writes one row per player per season to the BigQuery table `nba_underrated_score.player_scores`. A refresh replaces only the selected season: it reads the other seasons' rows, combines them with the new scores, and loads the result with a single `WRITE_TRUNCATE` job. This works on BigQuery's free tier, which does not allow DML statements, and leaves the table unchanged if the load fails. Column definitions are in the [data dictionary](DATA_DICTIONARY.md#bigquery-table-player_scores-formula-v21).

### Limitations specific to v2.1

- Percentile scaling makes every component relative to the current cohort, so scores are comparable within a season load and less so across loads.
- Estimated salaries partly derive from minutes and scoring, which also feed production and usage.
- Early-season samples are small; the scaled games-played gate reduces but does not remove that noise.
- On/off and lineup measures carry team and lineup context alongside individual impact.

---

## Intended use

*This section and those that follow describe the model v2 research edition.*

Generate hypotheses for player-value research using a transparent, reproducible ranking. The output is a scouting starting point, not a recommendation to sign a player. The project does not measure media attention, predict wins, infer causal player impact, or demonstrate an exploitable market inefficiency.

The repository name preserves the original project idea. The results use **heuristic value** language because "underrated" requires independent evidence of recognition that is not available here.

## Population and grain

One row per `PLAYER_ID` for one NBA regular season. The base table is the left side of one-to-one joins. Duplicate/null player IDs fail validation. Team labels come from the API's season aggregate record; traded players are not split into team stints, so team leaderboards should not be interpreted as team-specific performance.

The default cohort requires at least **20 games and 15 minutes per game**. These are analyst-chosen sample-size screens, not empirically optimized cutoffs. They reduce small-sample exposure without quantifying sampling uncertainty. The CLI can change both.

## Inputs and provenance

- NBA Stats via `nba_api`: base and advanced per-game statistics, plus overall defensive tracking.
- [Endpoint documentation](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/leaguedashplayerstats.md) and [defense schema](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/leaguedashptdefend.md).
- [NBA statistical glossary](https://www.nba.com/stats/help/glossary) for source metric definitions.
- Snapshots store selected source columns without salary estimates. Their manifest records request parameters, row counts, timestamp, and content hashes. Hashes detect changes; they do not independently establish source accuracy.
- Live runs save an input snapshot. Offline runs explicitly use `--snapshot`; they never silently substitute stale cached data.

The committed snapshot was acquired from the live endpoints on October 6, 2026. Base/advanced each contain 582 rows and defense contains 580. Raw API precision is retained. Selected columns are sufficient to reproduce this implementation, not every statistic on NBA.com.

## Score specification (v2)

Normalize each positive production measure to 0–100 with clipping. For metric `x` and benchmark `b`, `N(x,b) = clip(100*x/b, 0, 100)`.

| Component | Formula contribution |
| --- | --- |
| Efficiency | `0.15*N(TS%, .65) + 0.10*N(AST_TO, 4) + 0.15*clip((NET_RATING+20)/40*100, 0, 100)` |
| Role/workload proxy | `0.15*defense_score + 0.10*minutes_tier + 0.10*workload` |
| Multi-category contribution proxy | `0.10*N(PIE,.25) + 0.15*mean(N(PTS,25), N(AST,8), N(REB,10))` |

`production_value` sums these contributions. `workload` is the mean of `N(MIN,38)` and `N(USG_PCT,.35)`. Minutes tiers are 100 at ≥30 MPG, 90 at ≥25, 75 at ≥20, 60 at ≥15, and 50 otherwise.

`defense_score = clip((0.05 - PCT_PLUSMINUS) / 0.10 * 100, 0, 100)`. A difference of −0.05 means five percentage points below the reference field-goal percentage and receives 100; zero receives 50; +0.05 receives zero. Live data confirm fractional units: for example, the snapshot contains defended FG% .451, reference FG% .497, and differential −.046. Rounded source columns need not subtract exactly in every row.

The ±5-percentage-point span is a chosen benchmark, not a fitted effect size. Opponent shooting differential is noisy and does not directly quantify assignment difficulty. `--model legacy` changes only this defensive scale back to the original ±5.0 arithmetic; it does not undo v2 validation and clipping fixes.

The denominator is:

```text
salary_index      = 0.50 * max(5, SALARY / 50,000,000 * 100)
usage_opportunity = 0.15 * N(USG_PCT,.35) + 0.15 * N(MIN,38)
recognition_index = 0.20 * recognition_proxy
investment_index = max(15, salary_index + usage_opportunity + recognition_index)
score            = production_value / investment_index * performance_penalty
```

$50M is a fixed normalization benchmark, **not a claim about the current NBA maximum salary**. Salary is not capped at that benchmark.

Salary estimates: $25M for ≥32 MPG and ≥20 PPG; otherwise $15M for ≥28 MPG and ≥15 PPG; otherwise $10M for ≥25 MPG, $5M for ≥20 MPG, $2.5M for ≥10 MPG, and $1.5M below that. The salary floor makes $1.5M and $2.5M identical in the direct salary component.

Recognition proxy: 80 if salary ≥$20M and usage ≥25%; otherwise 60 if salary ≥$15M or usage ≥23%; otherwise 40 if salary ≥$10M; otherwise 20. It does not use awards, coverage, votes, or fan surveys.

Performance penalties apply in order: ×0.3 if net rating <−10 or TS% <40%; otherwise ×0.6 if net rating <−5; otherwise ×0.8 if net rating <0 and TS% <50%; otherwise ×1. These discontinuities are intentional heuristic choices and can create abrupt rank movements.

Score bands (≥2, ≥1.5, ≥1, below 1) are descriptive reference bands, not calibrated probabilities or validated categories. Tied scores share minimum ranks in exported league/team rankings.

## Quality rules

Required numerical inputs must be finite; minutes/count statistics must be nonnegative, salary positive, usage between 0 and 1, and TS% between 0 and 1.5. TS% can exceed 100% mathematically; the upper screen is a sanity limit, not an ordinary field-goal percentage constraint. Negative PIE is valid but contributes zero after clipping. Invalid required rows are excluded and counted.

Missing/non-finite optional PIE and defense receive a neutral score of 50 and explicit imputation flags. Defensive differentials outside [−1,1] are treated as invalid optional data. Neutral imputation can affect rankings and is not an estimate of the player's true ability.

For real salaries, supply `PLAYER_ID,SEASON,SALARY,SOURCE_URL`. Values must be positive annual USD, have source URLs, and cover every eligible player in the chosen season. Duplicate keys, season mismatch, and incomplete coverage fail; the pipeline never silently mixes provided salaries with estimates. A supplied URL records provenance but does not verify the salary's correctness or license.

## Sensitivity design

All scenarios use the identical scored cohort. Salary scenarios multiply every salary by 0.8 or 1.2 and recompute salary and recognition components. Other scenarios change the defensive span, remove recognition, or change production weights from 40/35/25 to 50/25/25. Production-only and points-per-game orderings provide simple descriptive baselines. Report Spearman rank correlation, top-20 overlap, and mean absolute rank movement. Top-k ties break by numeric player ID.

These are deterministic stress tests, not an uncertainty distribution. No p-values or predictive accuracy are claimed. Uniform salary scaling leaves relative salary errors untouched. The separate case study reports actual outputs, including results unfavorable to a strong "underrated" claim.

## Remaining research risks

1. Circular proxies: points/minutes determine estimated salaries and also enter production/opportunity.
2. Correlated inputs: PIE, net rating, efficiency, usage, and box-score production can double-count information.
3. Role/position bias: the model has no position-specific calibration or defensive matchup adjustment.
4. Team effects: net rating is contextual, not isolated individual impact.
5. No external target: neither recognition nor market value is independently measured.
6. One retrospective snapshot: no out-of-time generalization, ablation-based predictive comparison, or game-level uncertainty model has been evaluated.

## Next validation experiment

Acquire source-backed salaries and define an outcome before selecting weights. Freeze features as of a historical date, reserve later seasons for evaluation, benchmark against simple production/salary and minutes-based rules, and report rank agreement or ranking utility for that declared outcome with resampling appropriate to the data. Audit position, usage, and team subgroups. A model predicting future performance still would not automatically measure recognition.
