"""Offline behavior checks; no NBA API access required."""

import contextlib
import io
import unittest

import numpy as np
import pandas as pd

from nba_underrated_score import (
    add_salary_data,
    calculate_underrated_scores,
    merge_data,
    print_summary,
)


def sample():
    return pd.DataFrame(
        [
            {
                "PLAYER_ID": 1,
                "PLAYER_NAME": "Example Player",
                "TEAM_ABBREVIATION": "AAA",
                "GP": 40,
                "MIN": 20.0,
                "PTS": 10.0,
                "AST": 4.0,
                "REB": 5.0,
                "TS_PCT": 0.65,
                "AST_TO": 4.0,
                "NET_RATING": 0.0,
                "USG_PCT": 0.175,
                "PIE": 0.125,
                "PCT_PLUSMINUS": 0.0,
            }
        ]
    )


class ScoringTests(unittest.TestCase):
    def test_known_score_and_input_preservation(self):
        data = sample()
        before = data.copy(deep=True)
        result = calculate_underrated_scores(add_salary_data(data)).iloc[0]
        # Independently calculated baseline: production 64.63157894736842,
        # investment 24.39473684210526; no performance penalty.
        self.assertAlmostEqual(result["underrated_score"], 2.64940668824164)
        self.assertEqual(result["rating"], "High heuristic value")
        self.assertEqual(result["league_rank"], 1)
        pd.testing.assert_frame_equal(data, before)

    def test_optional_missing_values_receive_neutral_scores(self):
        data = sample()
        data.loc[0, ["PIE", "PCT_PLUSMINUS"]] = np.nan
        result = calculate_underrated_scores(add_salary_data(data)).iloc[0]
        self.assertEqual(result["position_flex"], 50)
        self.assertEqual(result["def_difficulty"], 50)

    def test_invalid_required_values_and_empty_summary(self):
        data = sample()
        data.loc[0, "TS_PCT"] = np.inf
        result = calculate_underrated_scores(add_salary_data(data))
        self.assertTrue(result.empty)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            print_summary(result)
        self.assertIn("No players qualified", output.getvalue())

    def test_duplicate_player_keys_rejected(self):
        base = sample()
        advanced = base[["PLAYER_ID", "TS_PCT", "AST_TO", "NET_RATING", "USG_PCT", "PIE"]]
        base = base.drop(columns=list(advanced.columns[1:]))
        with self.assertRaises(pd.errors.MergeError):
            merge_data(base, pd.concat([advanced, advanced]), None)


if __name__ == "__main__":
    unittest.main()
