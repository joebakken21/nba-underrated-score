"""Deterministic sensitivity analysis; stability is not predictive validation."""

from __future__ import annotations

import pandas as pd

from .scoring import ScoreSettings, calculate_underrated_scores


def sensitivity(
    inputs: pd.DataFrame, baseline: pd.DataFrame, top_k: int = 20
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if baseline.empty or top_k < 1:
        raise ValueError("Sensitivity requires scored players and a positive top_k")
    config = ScoreSettings()
    baseline = baseline.set_index("PLAYER_ID", drop=False)
    inputs = inputs.loc[inputs["PLAYER_ID"].isin(baseline.index)].copy()
    score = baseline["underrated_score"]
    variants = {"baseline_v2": score}
    for name, factor in (("salary_minus_20pct", 0.8), ("salary_plus_20pct", 1.2)):
        changed = inputs.copy()
        changed["SALARY"] *= factor
        variants[name] = calculate_underrated_scores(changed).set_index("PLAYER_ID")[
            "underrated_score"
        ]
    variants["legacy_defense_scale"] = calculate_underrated_scores(
        inputs, model="legacy"
    ).set_index("PLAYER_ID")["underrated_score"]
    variants["defense_span_10pp"] = calculate_underrated_scores(
        inputs, ScoreSettings(defense_span=0.10)
    ).set_index("PLAYER_ID")["underrated_score"]
    variants["no_recognition_proxy"] = (
        baseline["production_value"]
        / (baseline["salary_index"] + baseline["usage_opportunity"]).clip(
            lower=config.minimum_investment
        )
        * baseline["performance_penalty"]
    )
    variants["efficiency_weight_50pct"] = (
        (
            baseline["efficiency_composite"] / 0.40 * 0.50
            + baseline["role_difficulty"] / 0.35 * 0.25
            + baseline["versatility"]
        )
        / baseline["investment_index"]
        * baseline["performance_penalty"]
    )
    variants["production_only"] = baseline["production_value"]
    variants["points_per_game"] = baseline["PTS"]

    def top_ids(values):
        return set(
            values.sort_index().sort_values(ascending=False, kind="stable").head(top_k).index
        )

    base_top = top_ids(score)
    records, ranks = [], pd.DataFrame(index=baseline.index)
    for name, values in variants.items():
        values = values.reindex(baseline.index)
        ranked = values.rank(ascending=False, method="average")
        ranks[name] = ranked
        records.append(
            {
                "scenario": name,
                "players": len(values),
                "top_k": len(base_top),
                "rank_correlation": score.rank().corr(values.rank()) if len(values) > 1 else None,
                "top_k_overlap": len(base_top & top_ids(values)) / len(base_top),
                "mean_absolute_rank_change": (score.rank(ascending=False) - ranked).abs().mean(),
            }
        )
    ranks.insert(0, "PLAYER_NAME", baseline["PLAYER_NAME"])
    ranks.index.name = "PLAYER_ID"
    return pd.DataFrame(records), ranks.reset_index()
