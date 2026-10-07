"""Reproducible CLI: explicit data source, eligibility, provenance, and diagnostics."""

from __future__ import annotations

import argparse
import json
import logging
import platform
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .data import fetch_season, file_hash, load_snapshot, write_snapshot
from .diagnostics import sensitivity
from .export import print_summary, save_results
from .scoring import (
    DEFAULT_SEASON,
    ScoreSettings,
    add_salary_data,
    calculate_underrated_scores,
    merge_data,
)

LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reproducible NBA player-value research heuristic")
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument(
        "--snapshot", type=Path, help="Read a verified local snapshot instead of the NBA API"
    )
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    parser.add_argument("--min-minutes", type=float, default=15)
    parser.add_argument("--min-games", type=int, default=20)
    parser.add_argument(
        "--salary-file", type=Path, help="CSV: PLAYER_ID, SEASON, SALARY, SOURCE_URL"
    )
    parser.add_argument("--model", choices=["v2", "legacy"], default="v2")
    parser.add_argument(
        "--sensitivity", action="store_true", help="Compare assumptions on the same v2 cohort"
    )
    args = parser.parse_args(argv)
    if not np.isfinite(args.min_minutes) or args.min_minutes < 0 or args.min_games < 0:
        parser.error("Eligibility thresholds must be finite and nonnegative")
    if (
        not re.fullmatch(r"\d{4}-\d{2}", args.season)
        or int(args.season[-2:]) != (int(args.season[:4]) + 1) % 100
    ):
        parser.error("Season must be consecutive years, e.g. 2025-26")
    if args.sensitivity and args.model != "v2":
        parser.error("Sensitivity uses --model v2 as its baseline")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        if args.snapshot:
            tables, manifest = load_snapshot(args.snapshot, args.season)
        else:
            tables = fetch_season(args.season)
            manifest = write_snapshot(tables, args.output_dir / "input_snapshot", args.season)
        merged = merge_data(
            tables["base"], tables["advanced"], tables["defense"], args.min_minutes, args.min_games
        )
        salaries = pd.read_csv(args.salary_file) if args.salary_file else None
        inputs = add_salary_data(merged, salaries, args.season)
        results = calculate_underrated_scores(inputs, model=args.model)
        print_summary(results, args.season)
        if results.empty:
            LOGGER.error("No players qualified; no ranking files written")
            return 1
        save_results(results, args.season, args.output_dir)
        if args.sensitivity:
            summary, ranks = sensitivity(inputs, results)
            summary.to_csv(args.output_dir / "sensitivity.csv", index=False)
            ranks.to_csv(args.output_dir / "scenario_ranks.csv", index=False)
        run = {
            "project_version": __version__,
            "model": args.model,
            "run_at_utc": datetime.now(timezone.utc).isoformat(),
            "season": args.season,
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "eligibility": {"min_minutes": args.min_minutes, "min_games": args.min_games},
            "normalization": asdict(ScoreSettings()),
            "source_snapshot": manifest,
            "salary_mode": "provided" if args.salary_file else "estimated",
            "salary_file_sha256": file_hash(args.salary_file) if args.salary_file else None,
            "quality": {
                "base_rows": len(tables["base"]),
                "eligible_rows": len(merged),
                "scored_rows": len(results),
                "invalid_scoring_rows": len(inputs) - len(results),
                "defense_imputed_rows": int(results["defense_missing"].sum()),
                "pie_imputed_rows": int(results["pie_missing"].sum()),
            },
            "interpretation": "Exploratory heuristic; no predictive or causal validation. Recognition is a proxy.",
        }
        (args.output_dir / "run_manifest.json").write_text(
            json.dumps(run, indent=2) + "\n", encoding="utf-8"
        )
    except Exception:
        LOGGER.exception("NBA value pipeline failed")
        return 1
    return 0
