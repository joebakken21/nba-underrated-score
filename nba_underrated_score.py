"""Compatibility entry point for Spyder and direct script execution."""

from nba_value.cli import main
from nba_value.export import print_summary, save_results  # noqa: F401
from nba_value.scoring import (  # noqa: F401
    ScoreSettings,
    add_salary_data,
    calculate_underrated_scores,
    merge_data,
)

if __name__ == "__main__":
    raise SystemExit(main())
