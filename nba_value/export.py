"""CSV export and console summaries."""

import logging
import re
from pathlib import Path

import pandas as pd

from .scoring import DEFAULT_SEASON, RATINGS

LOGGER = logging.getLogger(__name__)


def save_results(
    df: pd.DataFrame, season: str = DEFAULT_SEASON, output_dir: str | Path = "."
) -> tuple[Path, Path]:
    destination = Path(output_dir)
    if not re.fullmatch(r"\d{4}-\d{2}", season):
        raise ValueError("Season must use YYYY-YY format")
    if not df["TEAM_ABBREVIATION"].astype(str).str.fullmatch(r"[A-Za-z0-9_-]{1,12}").all():
        raise ValueError("Invalid team abbreviation for export")
    destination.mkdir(parents=True, exist_ok=True)
    ranked = df.sort_values(
        ["underrated_score", "PLAYER_ID"], ascending=[False, True], kind="stable"
    )
    full_file = destination / f"nba_league_underrated_scores_{season}.csv"
    top_file = destination / f"nba_top_100_underrated_{season}.csv"
    ranked.to_csv(full_file, index=False)
    ranked.head(100).to_csv(top_file, index=False)
    for team, team_df in ranked.groupby("TEAM_ABBREVIATION"):
        team_df.to_csv(destination / f"{team}_underrated_{season}.csv", index=False)
    LOGGER.info("Exported %d players to %s", len(df), destination.resolve())
    return full_file, top_file


def print_summary(df: pd.DataFrame, season: str = DEFAULT_SEASON) -> None:
    print(f"\nNBA UNDERRATED SCORE ANALYSIS - {season} SEASON")
    print("Exploratory heuristic. See SALARY_SOURCE for salary provenance; recognition is a proxy.")
    if df.empty:
        print("No players qualified for scoring.")
        return
    print(f"Players: {len(df)} | Teams: {df['TEAM_ABBREVIATION'].nunique()}")
    print(
        f"Mean score: {df['underrated_score'].mean():.3f} | Median: {df['underrated_score'].median():.3f}"
    )
    print("\nRATING DISTRIBUTION:")
    counts = df["rating"].value_counts()
    for rating in RATINGS:
        count = counts.get(rating, 0)
        print(f"{rating}: {count} ({count / len(df):.1%})")
    print("\nTOP 10 MOST UNDERRATED:")
    for row in df.nlargest(10, "underrated_score").itertuples():
        print(
            f"{row.league_rank}. {row.PLAYER_NAME} ({row.TEAM_ABBREVIATION}) - {row.underrated_score:.2f}"
        )
    print("\nBEST VALUE BY TEAM (Top 10):")
    leaders = (
        df.sort_values("underrated_score", ascending=False)
        .drop_duplicates("TEAM_ABBREVIATION")
        .head(10)
    )
    for row in leaders.itertuples():
        print(f"{row.TEAM_ABBREVIATION}: {row.PLAYER_NAME} ({row.underrated_score:.2f})")
