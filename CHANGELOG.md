# Changelog

## 0.3.1 — Public dashboard on GitHub Pages

- Add a public dashboard at `docs/index.html`, served by GitHub Pages: scoreboard KPI cards, a top 25 leaderboard with a qualified/all toggle, a production-versus-investment chart, team hidden value, and the v2.1 methodology. It is one static page with no external libraries and uses team-color badges instead of logos.
- Add the 2026–27 snapshot it reads, `docs/data/player_scores_2026-27.csv` (407 players, loaded November 11, 2026).
- The loader now rewrites that snapshot on every run (`PAGES_EXPORT` in SETTINGS), with a clear stop if the file is locked or the docs folder is missing.

## 0.3.0 — Live 2026–27 pipeline and dashboard

- Add formula v2.1: Underrated Score = (Production Value x Performance Penalty) / max(Investment Index, 5), with percentile-scaled components, on/off efficiency, a carry-tax role measure, and decayed award recognition.
- Add qualifying gates: 30 games over a full season (scaled to games played so far), 15+ minutes per game, and Production Value of 50+.
- Rename tiers to Seriously Underrated, Quietly Valuable, Fairly Rated, and Properly Rated.
- Add the Spyder loader in `pipelines/`: NBA Stats API extraction with retries and a same-day cache, v2.1 scoring, CSV export, and a BigQuery load that replaces one season with `WRITE_TRUNCATE` on the free tier.
- Record the approximations used on every loaded row.
- Add the live dashboard, which reads the BigQuery table with read-only SQL and presents KPI cards, leaderboards, a production-versus-investment chart, and team hidden value.
- Add a `live` install option for the BigQuery packages.
- Document v2.1 in the methodology and the BigQuery columns in the data dictionary. The v2 research edition and its 2025–26 case study are unchanged.

## 0.2.0 — Portfolio research edition

- Separate pure scoring, API acquisition, exports, diagnostics, and CLI orchestration.
- Add a real 2025–26 snapshot, integrity checks, run manifests, and reproducible case study.
- Correct defensive percentage scaling: fractional ±0.05 corresponds to ±5 percentage points. Preserve the original defensive scale via `--model legacy` for comparison.
- Clip negative production proxies at zero; reject invalid keys and required numerical inputs.
- Flag neutral imputation and export salary provenance; support complete season-specific salary files.
- Change default eligibility from 5 MPG/no games threshold to 15 MPG/20 games.
- Replace unsupported recognition labels with descriptive heuristic score bands.
- Add nine assumption/baseline scenarios, 17 offline tests, and automated checks.

## 0.1.0 — Initial cleanup

Refactor the original script while preserving its scoring arithmetic on valid complete inputs. Add CLI options, one-to-one joins, optional missing-data handling, and basic offline tests.
