# NBA Underrated Score

A Python project that ranks NBA players using a custom **production value / investment index** score. It fetches per-game player statistics through `nba_api`, calculates league and team rankings, and exports CSV files.

## Setup

Requires Python 3.10 or newer.

```sh
python -m venv .venv
```

Activate the environment on Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

On macOS or Linux:

```sh
source .venv/bin/activate
```

Install dependencies:

```sh
python -m pip install -r requirements.txt
```

## Run

```sh
python nba_underrated_score.py --season 2025-26 --output-dir results
```

Optionally require a larger sample:

```sh
python nba_underrated_score.py --season 2025-26 --min-minutes 15 --min-games 20 --output-dir results
```

Defaults: season `2025-26`, at least five minutes per game, no minimum games threshold, and CSV output in the current working directory. Use `--help` to see the options. Running the file directly in Spyder uses these defaults.

## Scoring

| Production component | Weight | Inputs |
| --- | --- | --- |
| Efficiency | 40% | True shooting, assist-to-turnover ratio, net rating |
| Role difficulty | 35% | Defensive field-goal differential, minutes tier, workload |
| Versatility | 25% | PIE proxy and scoring, assists, rebounds |

| Investment component | Weight | Inputs |
| --- | --- | --- |
| Estimated salary | 50% | Salary tiers inferred from minutes and points |
| Opportunity | 30% | Minutes and usage rate |
| Estimated recognition | 20% | Salary and usage heuristic |

The production total is divided by the investment index, with additional penalties for low true shooting or negative net rating. Normalization benchmarks live in `ScoreSettings`; weights and tier thresholds are defined in the calculation functions.

| Score | Rating |
| --- | --- |
| 2.0 or higher | Seriously Underrated |
| 1.5 to below 2.0 | Quietly Valuable |
| 1.0 to below 1.5 | Fairly Rated |
| Below 1.0 | Properly Recognized |

These labels and thresholds are custom modeling choices, not validated assessments of public perception.

## Outputs

- `nba_league_underrated_scores_<season>.csv`: all scored players, highest score first.
- `nba_top_100_underrated_<season>.csv`: up to 100 highest-scoring players.
- `<TEAM>_underrated_<season>.csv`: rankings for each team.

Exports include the inputs and intermediate score components so rankings can be inspected. Tied scores share the same rank. The console displays rating counts, the top ten players, and the ten highest-scoring team leaders.

## Data handling and limitations

- Salary and recognition are estimates. This measures a custom value heuristic rather than observed market value or actual recognition.
- PIE is an impact proxy, not a direct measurement of positional flexibility. The scoring/passing/rebounding component averages contributions; it does not explicitly reward balance.
- The original defensive normalization is preserved. Its units and calibration need a separate review before interpreting that component as a validated measure of defensive difficulty.
- Missing optional defense or PIE values receive neutral scores. Missing or non-finite required scoring inputs exclude a player and produce a warning.
- Joins require one row per player ID; duplicate keys fail explicitly rather than multiplying rows.
- The NBA endpoints require network access and may fail or time out. Required-data failures stop execution; defense retrieval is optional. No automatic retries or caching are implemented.
- No CSVs are written when no players qualify. Existing files with matching names are overwritten on successful exports; other files from earlier runs are retained.

## Offline checks

```sh
python -m unittest discover -s tests -v
```

The tests use synthetic data and make no NBA API requests. Live API retrieval has not been verified as part of this cleanup.

## Project files

```text
nba_underrated_score.py  Data collection, scoring, exports, and CLI
requirements.txt       Runtime dependencies
tests/                 Offline scoring and data-handling checks
```
