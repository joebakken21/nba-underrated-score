"""Generate the checked-in case study and figure from an offline pipeline run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path("results"))
    parser.add_argument("--output", type=Path, default=Path("docs"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((args.results / "run_manifest.json").read_text())
    if (
        manifest["model"] != "v2"
        or manifest["salary_mode"] != "estimated"
        or manifest["eligibility"] != {"min_minutes": 15.0, "min_games": 20}
    ):
        raise ValueError("This case study requires the default v2 cohort and estimated salaries")
    season = manifest["season"]
    players = pd.read_csv(args.results / f"nba_league_underrated_scores_{season}.csv")
    scenarios = pd.read_csv(args.results / "sensitivity.csv")
    sensitivity = scenarios.set_index("scenario")
    selected = scenarios.loc[
        ~scenarios.scenario.isin(["baseline_v2", "production_only", "points_per_game"])
    ].copy()
    labels = {
        "salary_minus_20pct": "Salary estimates −20%",
        "salary_plus_20pct": "Salary estimates +20%",
        "legacy_defense_scale": "Original defensive scale",
        "defense_span_10pp": "Defense range ±10 pp",
        "no_recognition_proxy": "Remove recognition proxy",
        "efficiency_weight_50pct": "Efficiency weight 50%",
    }
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    fig, (ax, scatter) = plt.subplots(
        1, 2, figsize=(14, 5.6), gridspec_kw={"width_ratios": [1, 1.05]}
    )
    fig.patch.set_facecolor("#f7f9fc")
    ax.set_facecolor("#f7f9fc")
    scatter.set_facecolor("#f7f9fc")
    bars = ax.barh(
        [labels[s] for s in selected.scenario],
        selected.top_k_overlap * 100,
        color="#167d9a",
        height=0.58,
    )
    ax.invert_yaxis()
    ax.set_xlim(0, 112)
    ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    ax.set_xlabel("Overlap with baseline top 20")
    ax.set_title("How much does the shortlist change?", loc="left", fontweight="bold", pad=18)
    ax.bar_label(bars, labels=[f"{x:.0%}" for x in selected.top_k_overlap], padding=6)
    scatter.scatter(
        players.PTS, players.underrated_score, color="#167d9a", s=26, alpha=0.55, linewidths=0
    )
    scatter.set_xlabel("Points per game")
    scatter.set_ylabel("Heuristic value score")
    scatter.set_ylim(bottom=0)
    scatter.set_xlim(left=0)
    scatter.set_title("Value score is not a talent ranking", loc="left", fontweight="bold", pad=18)
    fig.suptitle(
        f"NBA VALUE LAB  /  {season}",
        x=0.03,
        ha="left",
        fontsize=20,
        fontweight="bold",
        color="#122238",
    )
    fig.text(
        0.03,
        0.025,
        f"{len(players)} players · ≥15 MPG and ≥20 games · Estimated salaries · Assumption sensitivity, not predictive validation",
        fontsize=10,
        color="#465467",
    )
    fig.tight_layout(rect=[0, 0.08, 1, 0.91], w_pad=3)
    fig.savefig(args.output / "sensitivity.png", dpi=170, facecolor=fig.get_facecolor())
    plt.close(fig)

    q = manifest["quality"]
    text = [
        f"# Case study: {season} player-value screening",
        "",
        "**Question:** Which players rise to the top of a transparent production-to-investment heuristic, and how dependent is that shortlist on the assumptions?",
        "",
        "This is an exploratory research result using observed NBA statistics and **estimated salaries**. It does not establish that these players are underpaid or overlooked.",
        "",
        "![Sensitivity analysis and scoring relationship](sensitivity.png)",
        "",
        "## Data and cohort",
        "",
        f"The snapshot contains {q['base_rows']} player-season rows from NBA Stats. The default filters retain **{len(players)} players** across **{players.TEAM_ABBREVIATION.nunique()} teams**, with at least 20 games and 15 minutes per game. {q['invalid_scoring_rows']} eligible rows failed required scoring validation; {q['defense_imputed_rows']} required neutral defense values and {q['pie_imputed_rows']} required neutral PIE values.",
        "",
        f"Snapshot recorded: `{manifest['source_snapshot']['retrieved_at_utc']}`. All inputs and SHA-256 hashes are in [data/snapshot](../data/snapshot). This is a fixed regular-season snapshot, not a live ranking.",
        "",
        "## What the sensitivity checks show",
        "",
        f"- Correcting the defensive units changes **{20 - int(round(sensitivity.loc['legacy_defense_scale', 'top_k_overlap'] * 20))} of the top 20 names** relative to the original defensive scale on this same cohort.",
        "- Scaling every estimated salary by ±20% retains the entire top 20 in both scenarios. This uniform perturbation does **not** test realistic, player-specific salary errors.",
        f"- Points per game and the heuristic have a rank correlation of **{sensitivity.loc['points_per_game', 'rank_correlation']:.3f}**. The investment denominator strongly changes the ordering. This is a warning against describing the output as an overall player-quality ranking.",
        "",
        "| Comparison | Rank correlation | Top-20 overlap | Mean absolute rank change |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in scenarios.itertuples():
        text.append(
            f"| {row.scenario} | {row.rank_correlation:.3f} | {row.top_k_overlap:.0%} | {row.mean_absolute_rank_change:.1f} |"
        )
    text += [
        "",
        "Rank correlation is Pearson correlation of average ranks (Spearman's rho); ties use average ranks. Top-20 membership breaks exact score ties by player ID. Comparisons share the same cohort. These are assumption scenarios, not confidence intervals or accuracy scores.",
        "",
        "## Leading candidates under this heuristic",
        "",
        "**Salary values below are model estimates, not player contracts.** Investigate candidates using verified compensation, role, film, and context before making decisions.",
        "",
        "| Rank | Player | Team | Games | MPG | Estimated salary | Score |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in players.head(10).itertuples():
        text.append(
            f"| {row.league_rank} | {row.PLAYER_NAME} | {row.TEAM_ABBREVIATION} | {row.GP} | {row.MIN:.1f} | ${row.SALARY / 1_000_000:.1f}M | {row.underrated_score:.3f} |"
        )
    text += [
        "",
        "## Interpretation and next experiment",
        "",
        "The implementation produces an auditable shortlist and exposes sensitivity to modeling decisions. Its main unresolved weakness is salary estimation from the same minutes and points used elsewhere in the model. The recognition proxy also reuses salary and usage. Apparent value can therefore reflect the model's construction rather than a real market inefficiency.",
        "",
        "The next research step is a player-ID-matched, season-specific salary dataset and a predeclared out-of-time evaluation. Freeze features before the evaluation season, compare against simple production/salary and minutes baselines, and assess next-season outcomes with uncertainty and positional subgroup checks. No such predictive evaluation has been performed here.",
        "",
        "## Reproduce",
        "",
        "```sh",
        "python -m nba_value --snapshot data/snapshot --sensitivity",
        "python scripts/build_case_study.py",
        "```",
        "",
        "Install the `plots` optional dependencies for the second command. The run manifest records model settings, eligibility, versions, input hashes, and exclusions. See [methodology](METHODOLOGY.md) and [data dictionary](DATA_DICTIONARY.md).",
        "",
    ]
    (args.output / "RESULTS.md").write_text("\n".join(text), encoding="utf-8")
    scenarios.to_csv(args.output / "sensitivity.csv", index=False)
    players.head(20).to_csv(args.output / "shortlist.csv", index=False)


if __name__ == "__main__":
    main()
