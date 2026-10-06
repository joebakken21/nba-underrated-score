"""Rank NBA players using a custom production-to-investment heuristic.

Salary and recognition are estimates, not observed financial or popularity data.
Run with --help for season, eligibility, and output-directory options.
"""

from __future__ import annotations

import argparse
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)
DEFAULT_SEASON = "2025-26"
RATINGS = (
    "Seriously Underrated", "Quietly Valuable", "Fairly Rated", "Properly Recognized"
)
BASE_COLUMNS = (
    "PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "TEAM_ABBREVIATION", "GP", "MIN",
    "PTS", "REB", "AST", "STL", "BLK", "TOV", "FG_PCT",
)
ADVANCED_COLUMNS = ("PLAYER_ID", "TS_PCT", "AST_TO", "NET_RATING", "USG_PCT", "PIE")
DEFENSE_COLUMNS = ("PLAYER_ID", "D_FG_PCT", "NORMAL_FG_PCT", "PCT_PLUSMINUS")
SCORING_COLUMNS = (
    "PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "MIN", "PTS", "REB", "AST",
    "TS_PCT", "AST_TO", "NET_RATING", "USG_PCT", "SALARY",
)


@dataclass(frozen=True)
class ScoreSettings:
    """Normalization benchmarks; component weights retain the original formula."""

    true_shooting: float = 0.65
    assist_turnover: float = 4.0
    net_rating_span: float = 20.0
    minutes: float = 38.0
    usage: float = 0.35
    player_impact: float = 0.25
    points: float = 25.0
    assists: float = 8.0
    rebounds: float = 10.0
    salary_benchmark: float = 50_000_000
    minimum_investment: float = 15.0

    def __post_init__(self) -> None:
        if any(not np.isfinite(value) or value <= 0 for value in vars(self).values()):
            raise ValueError("Scoring benchmarks must be finite and positive.")


def require_columns(df: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    missing = sorted(set(columns) - set(df.columns))
    if missing:
        raise ValueError(f"{label} is missing required columns: {', '.join(missing)}")


def select_columns(df: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    return df.loc[:, [column for column in columns if column in df.columns]].copy()


def get_league_stats(season: str, measure: str) -> pd.DataFrame:
    """Fetch a required stats table; API failures propagate to the CLI handler."""
    from nba_api.stats.endpoints import leaguedashplayerstats

    LOGGER.info("Pulling %s stats for %s...", measure.lower(), season)
    endpoint = leaguedashplayerstats.LeagueDashPlayerStats(
        season=season,
        measure_type_detailed_defense=measure,
        per_mode_detailed="PerGame",
        timeout=60,
    )
    df = endpoint.get_data_frames()[0]
    time.sleep(2)
    return select_columns(df, BASE_COLUMNS if measure == "Base" else ADVANCED_COLUMNS)


def get_league_base_stats(season: str = DEFAULT_SEASON) -> pd.DataFrame:
    return get_league_stats(season, "Base")


def get_league_advanced_stats(season: str = DEFAULT_SEASON) -> pd.DataFrame:
    return get_league_stats(season, "Advanced")


def get_league_defensive_stats(season: str = DEFAULT_SEASON) -> pd.DataFrame:
    """Defense is optional; report retrieval failures and use a neutral fallback."""
    from nba_api.stats.endpoints import leaguedashptdefend

    LOGGER.info("Pulling defensive stats...")
    try:
        endpoint = leaguedashptdefend.LeagueDashPtDefend(
            season=season, defense_category="Overall", timeout=60
        )
        df = endpoint.get_data_frames()[0]
        if "PLAYER_ID" not in df.columns:
            df = df.rename(columns={"CLOSE_DEF_PERSON_ID": "PLAYER_ID"})
        require_columns(df, ("PLAYER_ID",), "Defensive stats")
        return select_columns(df, DEFENSE_COLUMNS)
    except Exception as exc:
        # Optional external endpoint: continue even if its schema or service fails.
        LOGGER.warning("Could not retrieve defensive stats: %s", exc)
        return pd.DataFrame()
    finally:
        time.sleep(2)


def merge_data(
    base_df: pd.DataFrame,
    advanced_df: pd.DataFrame,
    defense_df: pd.DataFrame | None,
    min_minutes: float = 5,
    min_games: int = 0,
) -> pd.DataFrame:
    """Join one row per player and enforce explicit eligibility thresholds."""
    require_columns(base_df, ("PLAYER_ID", "MIN", "GP", "TEAM_ABBREVIATION"), "Base stats")
    require_columns(advanced_df, ("PLAYER_ID", "TS_PCT", "AST_TO", "NET_RATING", "USG_PCT"), "Advanced stats")
    merged = base_df.merge(
        select_columns(advanced_df, ADVANCED_COLUMNS),
        on="PLAYER_ID", how="left", validate="one_to_one",
    )
    if defense_df is not None and not defense_df.empty:
        merged = merged.merge(
            select_columns(defense_df, DEFENSE_COLUMNS),
            on="PLAYER_ID", how="left", validate="one_to_one",
        )
    merged = merged.loc[(merged["MIN"] >= min_minutes) & (merged["GP"] >= min_games)].copy()
    LOGGER.info("Eligible players: %d", len(merged))
    return merged


def add_salary_data(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the original salary tiers. Replace these estimates with real salaries later."""
    require_columns(df, ("MIN", "PTS"), "Salary inputs")
    players = df.copy()
    minutes, points = players["MIN"], players["PTS"]
    players["SALARY"] = np.select(
        [(minutes >= 32) & (points >= 20), (minutes >= 28) & (points >= 15),
         minutes >= 25, minutes >= 20, minutes >= 10],
        [25_000_000, 15_000_000, 10_000_000, 5_000_000, 2_500_000],
        default=1_500_000,
    )
    return players


def calculate_underrated_scores(
    df: pd.DataFrame, settings: ScoreSettings | None = None
) -> pd.DataFrame:
    """Compute the original weighted score without mutating the input table.

    Production: efficiency 40%, role difficulty 35%, versatility 25%.
    Investment: salary 50%, opportunity 30%, recognition heuristic 20%.
    Missing optional defense/PIE values receive neutral scores. Rows lacking
    required finite inputs are excluded with a warning.
    """
    require_columns(df, SCORING_COLUMNS, "Scoring inputs")
    config = settings or ScoreSettings()
    players = df.copy()
    numeric = list(SCORING_COLUMNS[3:])
    players[numeric] = players[numeric].apply(pd.to_numeric, errors="coerce")
    valid = np.isfinite(players[numeric]).all(axis=1)
    valid &= players[["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION"]].notna().all(axis=1)
    if not valid.all():
        LOGGER.warning("Excluding %d players with missing or invalid required inputs", (~valid).sum())
    players = players.loc[valid].copy()

    def normalized(column: str, benchmark: float) -> pd.Series:
        return (players[column] / benchmark * 100).clip(upper=100)

    def optional(column: str) -> pd.Series:
        values = players.get(column, pd.Series(np.nan, index=players.index))
        return pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)

    players["ts_score"] = normalized("TS_PCT", config.true_shooting)
    players["ast_tov_score"] = normalized("AST_TO", config.assist_turnover)
    players["net_rating_score"] = (
        (players["NET_RATING"] + config.net_rating_span) / (2 * config.net_rating_span) * 100
    ).clip(0, 100)
    players["efficiency_composite"] = (
        players["ts_score"] * 0.15 + players["ast_tov_score"] * 0.10
        + players["net_rating_score"] * 0.15
    )

    # Preserve the original defensive scale pending a separate model review.
    players["def_difficulty"] = ((5 - optional("PCT_PLUSMINUS")) / 10 * 100).clip(0, 100).fillna(50)
    minutes = players["MIN"]
    players["minutes_tier"] = np.select(
        [minutes >= 30, minutes >= 25, minutes >= 20, minutes >= 15],
        [100, 90, 75, 60], default=50,
    )
    players["minutes_norm"] = normalized("MIN", config.minutes)
    players["usage_norm"] = normalized("USG_PCT", config.usage)
    players["workload"] = (players["minutes_norm"] + players["usage_norm"]) / 2
    players["role_difficulty"] = (
        players["def_difficulty"] * 0.15 + players["minutes_tier"] * 0.10
        + players["workload"] * 0.10
    )

    # PIE is an impact proxy; it does not directly measure positional flexibility.
    players["position_flex"] = (optional("PIE") / config.player_impact * 100).clip(upper=100).fillna(50)
    players["pts_norm"] = normalized("PTS", config.points)
    players["ast_norm"] = normalized("AST", config.assists)
    players["reb_norm"] = normalized("REB", config.rebounds)
    players["role_diversity"] = players[["pts_norm", "ast_norm", "reb_norm"]].mean(axis=1)
    players["versatility"] = players["position_flex"] * 0.10 + players["role_diversity"] * 0.15
    players["production_value"] = (
        players["efficiency_composite"] + players["role_difficulty"] + players["versatility"]
    )

    players["salary_pct"] = (players["SALARY"] / config.salary_benchmark * 100).clip(lower=5)
    players["salary_index"] = players["salary_pct"] * 0.50
    players["usage_opportunity"] = players["usage_norm"] * 0.15 + players["minutes_norm"] * 0.15
    salary, usage = players["SALARY"], players["USG_PCT"]
    players["recognition_index"] = np.select(
        [(salary >= 20_000_000) & (usage >= 0.25),
         (salary >= 15_000_000) | (usage >= 0.23), salary >= 10_000_000],
        [80, 60, 40], default=20,
    ) * 0.20
    players["investment_index"] = (
        players["salary_index"] + players["usage_opportunity"] + players["recognition_index"]
    ).clip(lower=config.minimum_investment)

    net, ts = players["NET_RATING"], players["TS_PCT"]
    penalty = np.select(
        [(net < -10) | (ts < 0.40), net < -5, (net < 0) & (ts < 0.50)],
        [0.3, 0.6, 0.8], default=1.0,
    )
    players["underrated_score"] = players["production_value"] / players["investment_index"] * penalty
    score = players["underrated_score"]
    players["rating"] = np.select([score >= 2, score >= 1.5, score >= 1], RATINGS[:3], default=RATINGS[3])
    players["league_rank"] = score.rank(ascending=False, method="min").astype(int)
    players["team_rank"] = players.groupby("TEAM_ABBREVIATION")["underrated_score"].rank(
        ascending=False, method="min"
    ).astype(int)
    return players


def save_results(
    df: pd.DataFrame, season: str = DEFAULT_SEASON, output_dir: str | Path = "."
) -> tuple[Path, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    ranked = df.sort_values("underrated_score", ascending=False, kind="stable")
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
    print("Salary and recognition use estimates.")
    if df.empty:
        print("No players qualified for scoring.")
        return
    print(f"Players: {len(df)} | Teams: {df['TEAM_ABBREVIATION'].nunique()}")
    print(f"Mean score: {df['underrated_score'].mean():.3f} | Median: {df['underrated_score'].median():.3f}")
    print("\nRATING DISTRIBUTION:")
    counts = df["rating"].value_counts()
    for rating in RATINGS:
        count = counts.get(rating, 0)
        print(f"{rating}: {count} ({count / len(df):.1%})")
    print("\nTOP 10 MOST UNDERRATED:")
    for row in df.nlargest(10, "underrated_score").itertuples():
        print(f"{row.league_rank}. {row.PLAYER_NAME} ({row.TEAM_ABBREVIATION}) - {row.underrated_score:.2f}")
    print("\nBEST VALUE BY TEAM (Top 10):")
    leaders = df.sort_values("underrated_score", ascending=False).drop_duplicates("TEAM_ABBREVIATION").head(10)
    for row in leaders.itertuples():
        print(f"{row.TEAM_ABBREVIATION}: {row.PLAYER_NAME} ({row.underrated_score:.2f})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--output-dir", type=Path, default=Path("."))
    parser.add_argument("--min-minutes", type=float, default=5)
    parser.add_argument("--min-games", type=int, default=0)
    args = parser.parse_args(argv)
    if not np.isfinite(args.min_minutes) or args.min_minutes < 0 or args.min_games < 0:
        parser.error("Eligibility thresholds must be finite and nonnegative.")
    if not re.fullmatch(r"\d{4}-\d{2}", args.season):
        parser.error("Season must use YYYY-YY format, for example 2025-26.")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        base = get_league_base_stats(args.season)
        advanced = get_league_advanced_stats(args.season)
        if base.empty or advanced.empty:
            raise ValueError("The API returned no required player data.")
        defense = get_league_defensive_stats(args.season)
        merged = merge_data(base, advanced, defense, args.min_minutes, args.min_games)
        results = calculate_underrated_scores(add_salary_data(merged))
        print_summary(results, args.season)
        if results.empty:
            LOGGER.warning("No CSV files written because no players qualified.")
            return 1
        save_results(results, args.season, args.output_dir)
    except Exception:
        LOGGER.exception("NBA score generation failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
