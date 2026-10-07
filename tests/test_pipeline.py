"""Contract, edge-case, and integration checks using the committed NBA snapshot."""

import contextlib
import io
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from test_scoring import sample

from nba_value.cli import main
from nba_value.data import load_snapshot
from nba_value.diagnostics import sensitivity
from nba_value.scoring import (
    ScoreSettings,
    add_salary_data,
    calculate_underrated_scores,
    merge_data,
)

ROOT = Path(__file__).resolve().parents[1]


class Contracts(unittest.TestCase):
    def test_defense_units_and_legacy_comparison(self):
        for differential, expected in [(-0.05, 100), (0, 50), (0.05, 0)]:
            with self.subTest(differential=differential):
                data = sample()
                data["PCT_PLUSMINUS"] = differential
                data = add_salary_data(data)
                self.assertAlmostEqual(
                    calculate_underrated_scores(data).iloc[0].def_difficulty, expected
                )
                self.assertAlmostEqual(
                    calculate_underrated_scores(data, model="legacy").iloc[0].def_difficulty,
                    (5 - differential) * 10,
                )

    def test_penalty_boundaries(self):
        for net, ts, factor in [
            (-11, 0.60, 0.3),
            (-10, 0.60, 0.6),
            (-5, 0.60, 1),
            (-1, 0.49, 0.8),
            (1, 0.39, 0.3),
        ]:
            with self.subTest(net=net, ts=ts):
                data = sample().assign(NET_RATING=net, TS_PCT=ts)
                row = calculate_underrated_scores(add_salary_data(data)).iloc[0]
                self.assertEqual(row.performance_penalty, factor)
                self.assertAlmostEqual(
                    row.underrated_score, row.production_value / row.investment_index * factor
                )

    def test_invalid_settings(self):
        for value in [0, -1, np.inf, np.nan]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                ScoreSettings(defense_span=value)

    def test_null_ids_cannot_join_each_other(self):
        with self.assertRaises(ValueError):
            calculate_underrated_scores(add_salary_data(sample().assign(PLAYER_ID=np.nan)))

    def test_salary_provenance_and_complete_coverage(self):
        salary = pd.DataFrame(
            [
                {
                    "PLAYER_ID": 1,
                    "SEASON": "2025-26",
                    "SALARY": 8_000_000,
                    "SOURCE_URL": "https://example.org/salary",
                }
            ]
        )
        result = add_salary_data(sample(), salary)
        self.assertEqual(result.iloc[0].SALARY, 8_000_000)
        self.assertEqual(result.iloc[0].SALARY_SOURCE, "https://example.org/salary")
        with self.assertRaises(ValueError):
            add_salary_data(sample(), salary.assign(SEASON="2024-25"))
        with self.assertRaises(pd.errors.MergeError):
            add_salary_data(sample(), pd.concat([salary, salary]))

    def test_salary_tier_boundaries(self):
        data = pd.concat([sample()] * 4, ignore_index=True)
        data["MIN"] = [9.9, 10, 19.9, 20]
        self.assertEqual(
            add_salary_data(data).SALARY.tolist(), [1_500_000, 2_500_000, 2_500_000, 5_000_000]
        )

    def test_snapshot_season_mismatch(self):
        with self.assertRaises(ValueError):
            load_snapshot(ROOT / "data/snapshot", "2024-25")

    def test_snapshot_tampering(self):
        with (
            patch("nba_value.data.file_hash", return_value="tampered"),
            self.assertRaises(ValueError),
        ):
            load_snapshot(ROOT / "data/snapshot", "2025-26")

    def test_cli_invalid_season(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(["--season", "2025-99"])
        self.assertEqual(error.exception.code, 2)


class SnapshotIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables, _ = load_snapshot(ROOT / "data/snapshot", "2025-26")
        cls.merged = merge_data(
            cls.tables["base"], cls.tables["advanced"], cls.tables["defense"], 15, 20
        )
        cls.inputs = add_salary_data(cls.merged)
        cls.results = calculate_underrated_scores(cls.inputs)

    def test_cohort_and_finite_scores(self):
        self.assertEqual(len(self.tables["base"]), 582)
        self.assertEqual(len(self.results), 350)
        self.assertEqual(self.results.PLAYER_ID.nunique(), 350)
        self.assertTrue(np.isfinite(self.results.underrated_score).all())
        self.assertTrue((self.results.underrated_score >= 0).all())
        self.assertTrue((self.results.GP >= 20).all())
        self.assertTrue((self.results.MIN >= 15).all())

    def test_deterministic_scoring_after_shuffle(self):
        shuffled = calculate_underrated_scores(self.inputs.sample(frac=1, random_state=7))
        columns = ["underrated_score", "league_rank", "team_rank"]
        pd.testing.assert_frame_equal(
            self.results.set_index("PLAYER_ID")[columns].sort_index(),
            shuffled.set_index("PLAYER_ID")[columns].sort_index(),
        )

    def test_sensitivity_baseline_and_matched_cohorts(self):
        summary, ranks = sensitivity(self.inputs, self.results)
        self.assertEqual(len(summary), 9)
        self.assertTrue((summary.players == 350).all())
        self.assertEqual(summary.iloc[0].top_k_overlap, 1)
        self.assertAlmostEqual(summary.iloc[0].rank_correlation, 1)
        self.assertTrue(summary.top_k_overlap.between(0, 1).all())
        self.assertEqual(len(ranks), 350)

    def test_stricter_eligibility_is_subset(self):
        strict = merge_data(
            self.tables["base"], self.tables["advanced"], self.tables["defense"], 20, 40
        )
        self.assertTrue(set(strict.PLAYER_ID).issubset(set(self.merged.PLAYER_ID)))


if __name__ == "__main__":
    unittest.main()
