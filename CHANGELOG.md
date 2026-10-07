# Changelog

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
