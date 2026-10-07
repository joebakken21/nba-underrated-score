"""Pure, inspectable scoring transformations. No network or file I/O."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)
DEFAULT_SEASON = "2025-26"
RATINGS = ("High heuristic value", "Above reference", "Near reference", "Below reference")
BASE_COLUMNS = (
    "PLAYER_ID",
    "PLAYER_NAME",
    "TEAM_ID",
    "TEAM_ABBREVIATION",
    "GP",
    "MIN",
    "PTS",
    "REB",
    "AST",
    "STL",
    "BLK",
    "TOV",
    "FG_PCT",
)
ADVANCED_COLUMNS = ("PLAYER_ID", "TS_PCT", "AST_TO", "NET_RATING", "USG_PCT", "PIE")
DEFENSE_COLUMNS = ("PLAYER_ID", "D_FG_PCT", "NORMAL_FG_PCT", "PCT_PLUSMINUS")
SCORING_COLUMNS = (
    "PLAYER_ID",
    "PLAYER_NAME",
    "TEAM_ABBREVIATION",
    "MIN",
    "PTS",
    "REB",
    "AST",
    "TS_PCT",
    "AST_TO",
    "NET_RATING",
    "USG_PCT",
    "SALARY",
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
    defense_span: float = 0.05

    def __post_init__(self) -> None:
        if any(not np.isfinite(value) or value <= 0 for value in vars(self).values()):
            raise ValueError("Scoring benchmarks must be finite and positive.")


def require_columns(df: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    missing = sorted(set(columns) - set(df.columns))
    if missing:
        raise ValueError(f"{label} is missing required columns: {', '.join(missing)}")


def select_columns(df: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    return df.loc[:, [column for column in columns if column in df.columns]].copy()


def validate_keys(df: pd.DataFrame, label: str) -> None:
    require_columns(df, ("PLAYER_ID",), label)
    keys = pd.to_numeric(df["PLAYER_ID"], errors="coerce")
    if (
        keys.isna().any()
        or not np.isfinite(keys).all()
        or (keys <= 0).any()
        or (keys % 1 != 0).any()
    ):
        raise ValueError(f"{label}: PLAYER_ID must be positive integers without missing values")
    if keys.duplicated().any():
        raise pd.errors.MergeError(f"{label}: duplicate PLAYER_ID values")


def merge_data(
    base_df: pd.DataFrame,
    advanced_df: pd.DataFrame,
    defense_df: pd.DataFrame | None,
    min_minutes: float = 5,
    min_games: int = 0,
) -> pd.DataFrame:
    """Join one row per player and enforce explicit eligibility thresholds."""
    if not np.isfinite(min_minutes) or min_minutes < 0 or min_games < 0:
        raise ValueError("Eligibility thresholds must be finite and nonnegative")
    validate_keys(base_df, "Base stats")
    validate_keys(advanced_df, "Advanced stats")
    require_columns(base_df, ("PLAYER_ID", "MIN", "GP", "TEAM_ABBREVIATION"), "Base stats")
    require_columns(
        advanced_df, ("PLAYER_ID", "TS_PCT", "AST_TO", "NET_RATING", "USG_PCT"), "Advanced stats"
    )
    merged = base_df.merge(
        select_columns(advanced_df, ADVANCED_COLUMNS),
        on="PLAYER_ID",
        how="left",
        validate="one_to_one",
    )
    if defense_df is not None and not defense_df.empty:
        validate_keys(defense_df, "Defensive stats")
        merged = merged.merge(
            select_columns(defense_df, DEFENSE_COLUMNS),
            on="PLAYER_ID",
            how="left",
            validate="one_to_one",
        )
    for column in ("MIN", "GP"):
        merged[column] = pd.to_numeric(merged[column], errors="coerce")
    merged = merged.loc[(merged["MIN"] >= min_minutes) & (merged["GP"] >= min_games)].copy()
    LOGGER.info("Eligible players: %d", len(merged))
    return merged


def add_salary_data(
    df: pd.DataFrame, salaries: pd.DataFrame | None = None, season: str = DEFAULT_SEASON
) -> pd.DataFrame:
    """Apply the original salary tiers. Replace these estimates with real salaries later."""
    require_columns(df, ("MIN", "PTS"), "Salary inputs")
    players = df.copy()
    if salaries is not None:
        require_columns(salaries, ("PLAYER_ID", "SEASON", "SALARY", "SOURCE_URL"), "Salaries")
        selected = salaries.loc[salaries["SEASON"] == season].copy()
        validate_keys(selected, "Salaries for selected season")
        selected["SALARY"] = pd.to_numeric(selected["SALARY"], errors="coerce")
        if not (np.isfinite(selected["SALARY"]) & (selected["SALARY"] > 0)).all():
            raise ValueError("Salaries must be positive finite annual USD amounts")
        if not selected["SOURCE_URL"].fillna("").str.match(r"https?://\S+").all():
            raise ValueError("Every supplied salary requires a source URL")
        players = players.drop(columns=["SALARY", "SALARY_SOURCE"], errors="ignore").merge(
            selected[["PLAYER_ID", "SALARY", "SOURCE_URL"]].rename(
                columns={"SOURCE_URL": "SALARY_SOURCE"}
            ),
            on="PLAYER_ID",
            how="left",
            validate="one_to_one",
        )
        if players["SALARY"].isna().any():
            raise ValueError(
                "Salary file does not cover every eligible player; no estimates are silently mixed in"
            )
        return players
    minutes, points = players["MIN"], players["PTS"]
    players["SALARY"] = np.select(
        [
            (minutes >= 32) & (points >= 20),
            (minutes >= 28) & (points >= 15),
            minutes >= 25,
            minutes >= 20,
            minutes >= 10,
        ],
        [25_000_000, 15_000_000, 10_000_000, 5_000_000, 2_500_000],
        default=1_500_000,
    )
    players["SALARY_SOURCE"] = "estimated_from_minutes_and_points"
    return players


def calculate_underrated_scores(
    df: pd.DataFrame, settings: ScoreSettings | None = None, *, model: str = "v2"
) -> pd.DataFrame:
    """Compute a versioned heuristic without mutating the input table.

    Production: efficiency 40%, role difficulty 35%, versatility 25%.
    Investment: salary 50%, opportunity 30%, recognition heuristic 20%.
    Missing optional defense/PIE values receive neutral scores. Rows lacking
    required finite inputs are excluded with a warning.
    """
    require_columns(df, SCORING_COLUMNS, "Scoring inputs")
    validate_keys(df, "Scoring inputs")
    if model not in {"v2", "legacy"}:
        raise ValueError("model must be v2 or legacy")
    config = settings or ScoreSettings()
    players = df.copy()
    numeric = list(SCORING_COLUMNS[3:])
    players[numeric] = players[numeric].apply(pd.to_numeric, errors="coerce")
    valid = np.isfinite(players[numeric]).all(axis=1)
    valid &= players[["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION"]].notna().all(axis=1)
    for column in ("MIN", "PTS", "REB", "AST", "AST_TO"):
        valid &= players[column] >= 0
    valid &= (players["SALARY"] > 0) & players["USG_PCT"].between(0, 1)
    valid &= players["TS_PCT"].between(0, 1.5)
    if not valid.all():
        LOGGER.warning(
            "Excluding %d players with missing or invalid required inputs", (~valid).sum()
        )
    players = players.loc[valid].copy()

    def normalized(column: str, benchmark: float) -> pd.Series:
        return (players[column] / benchmark * 100).clip(0, 100)

    def optional(column: str) -> pd.Series:
        values = players.get(column, pd.Series(np.nan, index=players.index))
        return pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)

    players["ts_score"] = normalized("TS_PCT", config.true_shooting)
    players["ast_tov_score"] = normalized("AST_TO", config.assist_turnover)
    players["net_rating_score"] = (
        (players["NET_RATING"] + config.net_rating_span) / (2 * config.net_rating_span) * 100
    ).clip(0, 100)
    players["efficiency_composite"] = (
        players["ts_score"] * 0.15
        + players["ast_tov_score"] * 0.10
        + players["net_rating_score"] * 0.15
    )

    # API fractions: -0.05 means five percentage points below normal FG%.
    span = 5.0 if model == "legacy" else config.defense_span
    defense = optional("PCT_PLUSMINUS").where(lambda values: values.between(-1, 1))
    players["defense_missing"] = defense.isna()
    players["def_difficulty"] = ((span - defense) / (2 * span) * 100).clip(0, 100).fillna(50)
    minutes = players["MIN"]
    players["minutes_tier"] = np.select(
        [minutes >= 30, minutes >= 25, minutes >= 20, minutes >= 15],
        [100, 90, 75, 60],
        default=50,
    )
    players["minutes_norm"] = normalized("MIN", config.minutes)
    players["usage_norm"] = normalized("USG_PCT", config.usage)
    players["workload"] = (players["minutes_norm"] + players["usage_norm"]) / 2
    players["role_difficulty"] = (
        players["def_difficulty"] * 0.15
        + players["minutes_tier"] * 0.10
        + players["workload"] * 0.10
    )

    # PIE is an impact proxy; it does not directly measure positional flexibility.
    players["pie_missing"] = optional("PIE").isna()
    players["position_flex"] = (
        (optional("PIE") / config.player_impact * 100).clip(0, 100).fillna(50)
    )
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
    players["recognition_index"] = (
        np.select(
            [
                (salary >= 20_000_000) & (usage >= 0.25),
                (salary >= 15_000_000) | (usage >= 0.23),
                salary >= 10_000_000,
            ],
            [80, 60, 40],
            default=20,
        )
        * 0.20
    )
    players["investment_index"] = (
        players["salary_index"] + players["usage_opportunity"] + players["recognition_index"]
    ).clip(lower=config.minimum_investment)

    net, ts = players["NET_RATING"], players["TS_PCT"]
    penalty = np.select(
        [(net < -10) | (ts < 0.40), net < -5, (net < 0) & (ts < 0.50)],
        [0.3, 0.6, 0.8],
        default=1.0,
    )
    players["performance_penalty"] = penalty
    players["underrated_score"] = (
        players["production_value"] / players["investment_index"] * penalty
    )
    players["model_version"] = model
    score = players["underrated_score"]
    players["rating"] = np.select(
        [score >= 2, score >= 1.5, score >= 1], RATINGS[:3], default=RATINGS[3]
    )
    players["league_rank"] = score.rank(ascending=False, method="min").astype(int)
    players["team_rank"] = (
        players.groupby("TEAM_ABBREVIATION")["underrated_score"]
        .rank(ascending=False, method="min")
        .astype(int)
    )
    return players
