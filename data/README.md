# Data provenance

`snapshot/` is a fixed 2025–26 regular-season extraction from NBA Stats, acquired through `nba_api` on October 6, 2026. It is real source data, not synthetic demonstration data.

| File | Endpoint | Scope |
| --- | --- | --- |
| base.csv | leaguedashplayerstats | Base, PerGame, Regular Season |
| advanced.csv | leaguedashplayerstats | Advanced, PerGame, Regular Season |
| defense.csv | leaguedashptdefend | Overall defense, Totals, Regular Season |

Only columns used or retained by the pipeline are included. Defense's player key is renamed from `CLOSE_DEF_PERSON_ID` to `PLAYER_ID`. The source timestamp and per-file SHA-256 hashes are in `manifest.json`. Defense rate fields remain fractional rates even though its endpoint's count mode is Totals.

The snapshot contains no actual salaries. Salary estimates are added at runtime and labeled in the output. NBA statistics and third-party data are not covered by an implied project data license. Consult the source's terms before redistributing or using the data commercially.

To refresh, run the CLI without `--snapshot`; the resulting directory includes a new `input_snapshot`. Refreshing the committed snapshot requires regenerating the case study and reviewing the pinned-cohort tests. Do not overwrite inputs merely to make an existing result appear current.
