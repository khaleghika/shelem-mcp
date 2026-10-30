"""Unit tests for the standalone Shelem scoring engine.

The band table in the original skill (5–40 success, 45–80 failure) is not
the oracle. Worked examples, the Mak rule, and the 1000-point examples are.
These tests do not import MCP.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shelem_mcp import scoring as ENGINE

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "shelem_mcp"


def engine_env():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(ROOT / "src"), env.get("PYTHONPATH")])
    )
    return env


ENGINE_COMMAND = [sys.executable, "-m", "shelem_mcp.scoring"]


def score(**overrides):
    payload = {
        "team1_score": 0,
        "team2_score": 0,
        "bidding_team": 1,
        "hakem_team": 1,
    }
    payload.update(overrides)
    return ENGINE.calculate(payload)


def expect_error(testcase, payload, field):
    with testcase.assertRaises(ENGINE.ScoreInputError) as caught:
        ENGINE.calculate(payload)
    testcase.assertEqual(caught.exception.field, field)
    return str(caught.exception)


class OriginalExamplesTest(unittest.TestCase):
    def test_example_1_bid_made_inside_the_old_success_band(self):
        result = score(bid=140, defending_points=25, declarer_points=140)
        self.assertEqual(result["team1_delta"], 140)
        self.assertEqual(result["team2_delta"], 25)
        self.assertEqual(result["scoring_rule"], "bid_made")
        self.assertTrue(result["bid_successful"])

    def test_example_2_failure_contradicts_the_5_to_40_band(self):
        # Bid 135, defenders captured 35, declarer captured 130.
        # The band table awards +135. The worked example awards -135.
        result = score(bid=135, defending_points=35, declarer_points=130)
        self.assertEqual(result["team1_delta"], -135)
        self.assertEqual(result["team2_delta"], 35)
        self.assertEqual(result["scoring_rule"], "bid_failed")
        self.assertFalse(result["bid_successful"])

    def test_example_3_small_defensive_capture(self):
        result = score(bid=140, defending_points=10)
        self.assertEqual((result["team1_delta"], result["team2_delta"]), (140, 10))

    def test_example_4_heavy_failure(self):
        result = score(bid=120, defending_points=90)
        self.assertEqual(result["team1_delta"], -240)
        self.assertEqual(result["team2_delta"], 90)
        self.assertEqual(result["scoring_rule"], "heavy_failure")

    def test_section_6_opponents_bid_135_and_we_captured_35(self):
        result = score(bidding_team=2, hakem_team=2, bid=135, defending_points=35)
        self.assertEqual(result["team1_delta"], 35)
        self.assertEqual(result["team2_delta"], -135)
        self.assertEqual(result["defending_team"], 1)

    def test_mak_is_a_made_bid_not_a_failure(self):
        result = score(bid=140, outcome="mak")
        self.assertEqual(result["defending_points"], 25)
        self.assertEqual(result["declarer_points"], 140)
        self.assertEqual((result["team1_delta"], result["team2_delta"]), (140, 25))
        self.assertTrue(result["bid_successful"])

    def test_sweep_on_a_normal_bid_of_130_doubles_the_bid(self):
        result = score(bid=130, outcome="sweep")
        self.assertEqual(result["defending_points"], 0)
        self.assertEqual(result["team1_delta"], 260)
        self.assertEqual(result["team2_delta"], 0)
        self.assertEqual(result["scoring_rule"], "sweep_double")


class ShelemContractTest(unittest.TestCase):
    def test_shelem_success_is_330(self):
        result = score(bid=165, contract="shelem", defending_points=0)
        self.assertEqual(result["team1_delta"], 330)
        self.assertEqual(result["team2_delta"], 0)
        self.assertEqual(result["scoring_rule"], "shelem_made")

    def test_shelem_failure_boundaries(self):
        for defending in (5, 40, 45, 80):
            with self.subTest(defending=defending):
                result = score(bid=165, contract="shelem", defending_points=defending)
                self.assertEqual(result["team1_delta"], -330)
                self.assertEqual(result["team2_delta"], defending)
                self.assertEqual(result["scoring_rule"], "shelem_failed")

    def test_shelem_heavy_failure_boundaries(self):
        for defending in (85, 90, 165):
            with self.subTest(defending=defending):
                result = score(bid=165, contract="shelem", defending_points=defending)
                self.assertEqual(result["team1_delta"], -660)
                self.assertEqual(result["team2_delta"], defending)
                self.assertEqual(result["scoring_rule"], "shelem_heavy_failure")

    def test_sare_shelem_matches_shelem(self):
        shelem = score(bid=165, contract="shelem", defending_points=10)
        sare = score(bid=165, contract="sare-shelem", defending_points=10)
        self.assertEqual(shelem["team1_delta"], sare["team1_delta"])
        self.assertEqual(shelem["team2_delta"], sare["team2_delta"])
        self.assertEqual(sare["contract"], "sare-shelem")
        self.assertEqual(sare["team1_delta"], -330)

    def test_normal_165_uses_the_general_failure_penalty(self):
        result = score(bid=165, contract="normal", defending_points=10)
        self.assertEqual(result["team1_delta"], -165)
        self.assertEqual(result["scoring_rule"], "bid_failed")
        heavy = score(bid=165, contract="normal", defending_points=85)
        self.assertEqual(heavy["team1_delta"], -330)
        self.assertEqual(heavy["scoring_rule"], "heavy_failure")
        made = score(bid=165, contract="normal", defending_points=0)
        self.assertEqual(made["team1_delta"], 330)
        self.assertEqual(made["scoring_rule"], "sweep_double")

    def test_bid_165_without_a_contract_is_rejected(self):
        message = expect_error(
            self,
            {"team1_score": 0, "team2_score": 0, "bidding_team": 1, "bid": 165, "defending_points": 0},
            "contract",
        )
        self.assertIn("shelem", message)
        self.assertIn("normal", message)

    def test_shelem_contract_requires_bid_165(self):
        expect_error(
            self,
            {
                "team1_score": 0,
                "team2_score": 0,
                "bidding_team": 1,
                "bid": 160,
                "contract": "shelem",
                "defending_points": 0,
            },
            "contract",
        )


class ThousandPointRuleTest(unittest.TestCase):
    def test_defender_above_1000_receives_nothing_when_the_bid_is_made(self):
        result = score(
            team1_score=1100,
            team2_score=70,
            bidding_team=2,
            hakem_team=2,
            bid=140,
            defending_points=10,
        )
        self.assertEqual(result["team1_delta"], 0)
        self.assertEqual(result["team2_delta"], 140)
        self.assertEqual(result["team1_score"], 1100)
        self.assertEqual(result["team2_score"], 210)
        self.assertTrue(result["thousand_point_rule_applied"])
        self.assertIsNone(result["winner"])

    def test_defender_above_1000_keeps_captured_points_when_the_bid_fails(self):
        result = score(
            team1_score=1100,
            team2_score=70,
            bidding_team=2,
            hakem_team=2,
            bid=140,
            defending_points=35,
        )
        self.assertEqual(result["team1_delta"], 35)
        self.assertEqual(result["team2_delta"], -140)
        self.assertEqual(result["team1_score"], 1135)
        self.assertEqual(result["team2_score"], -70)
        self.assertFalse(result["thousand_point_rule_applied"])
        self.assertFalse(result["bid_successful"])

    def test_declarer_above_1000_is_scored_without_modification(self):
        result = score(
            team1_score=1100,
            team2_score=70,
            bid=140,
            defending_points=25,
        )
        self.assertEqual(result["team1_delta"], 140)
        self.assertEqual(result["team2_delta"], 25)
        self.assertEqual(result["team1_score"], 1240)
        self.assertEqual(result["team2_score"], 95)
        self.assertFalse(result["thousand_point_rule_applied"])
        self.assertEqual(result["winner"], 1)
        self.assertTrue(result["game_finished"])

    def test_exactly_1000_is_inside_the_rule(self):
        result = score(team1_score=400, team2_score=1000, bid=140, defending_points=25)
        self.assertEqual(result["team2_delta"], 0)
        self.assertTrue(result["thousand_point_rule_applied"])

    def test_999_is_outside_the_rule(self):
        result = score(team1_score=400, team2_score=999, bid=140, defending_points=25)
        self.assertEqual(result["team2_delta"], 25)
        self.assertFalse(result["thousand_point_rule_applied"])

    def test_hakem_below_1000_and_defender_below_1000(self):
        result = score(team1_score=500, team2_score=480, bid=120, defending_points=20)
        self.assertEqual((result["team1_delta"], result["team2_delta"]), (120, 20))
        self.assertFalse(result["thousand_point_rule_applied"])

    def test_hakem_below_1000_while_the_other_team_is_at_1000(self):
        result = score(team1_score=500, team2_score=1000, bid=140, defending_points=10)
        self.assertEqual(result["hakem_team"], 1)
        self.assertEqual(result["team1_score"], 640)
        self.assertEqual(result["team2_score"], 1000)
        self.assertTrue(result["thousand_point_rule_applied"])

    def test_hakem_at_1000_does_not_change_a_failed_bid(self):
        result = score(team1_score=1000, team2_score=200, bid=140, defending_points=35)
        self.assertEqual(result["team1_delta"], -140)
        self.assertEqual(result["team2_delta"], 35)
        self.assertFalse(result["thousand_point_rule_applied"])

    def test_both_teams_at_or_above_1000_and_the_bid_fails(self):
        result = score(team1_score=1000, team2_score=1050, bid=140, defending_points=35)
        self.assertEqual(result["team1_score"], 860)
        self.assertEqual(result["team2_score"], 1085)
        self.assertFalse(result["thousand_point_rule_applied"])

    def test_sweep_does_not_mark_the_rule_applied_when_defenders_already_score_zero(self):
        result = score(team1_score=200, team2_score=1100, bid=130, outcome="sweep")
        self.assertEqual(result["team2_delta"], 0)
        self.assertFalse(result["thousand_point_rule_applied"])

    def test_shelem_failure_still_pays_a_defender_at_1000(self):
        result = score(
            team1_score=100,
            team2_score=1100,
            bid=165,
            contract="shelem",
            defending_points=10,
        )
        self.assertEqual(result["team1_delta"], -330)
        self.assertEqual(result["team2_delta"], 10)
        self.assertFalse(result["thousand_point_rule_applied"])

    def test_rule_uses_the_score_before_each_hand(self):
        first = score(team1_score=880, team2_score=1000, bid=120, defending_points=40)
        self.assertEqual((first["team1_score"], first["team2_score"]), (1000, 1000))
        second = score(
            team1_score=first["team1_score"],
            team2_score=first["team2_score"],
            bid=120,
            outcome="mak",
        )
        self.assertEqual((second["team1_score"], second["team2_score"]), (1120, 1000))


class BandConflictTest(unittest.TestCase):
    def test_made_bid_with_45_defending_points_is_not_a_failure(self):
        result = score(bid=120, defending_points=45)
        self.assertEqual(result["team1_delta"], 120)
        self.assertEqual(result["scoring_rule"], "bid_made")

    def test_low_bid_made_with_defending_points_in_the_old_failure_band(self):
        result = score(bid=100, defending_points=65)
        self.assertEqual(result["declarer_points"], 100)
        self.assertEqual(result["team1_delta"], 100)
        self.assertEqual(result["team2_delta"], 65)

    def test_high_bid_missed_inside_the_old_success_band(self):
        result = score(bid=150, defending_points=20)
        self.assertEqual(result["declarer_points"], 145)
        self.assertEqual(result["team1_delta"], -150)
        self.assertEqual(result["scoring_rule"], "bid_failed")

    def test_single_and_heavy_failure_boundary(self):
        single = score(bid=100, defending_points=80)
        heavy = score(bid=100, defending_points=85)
        self.assertEqual(single["team1_delta"], -100)
        self.assertEqual(heavy["team1_delta"], -200)

    def test_team_two_can_be_the_declarer(self):
        result = score(bidding_team=2, hakem_team=2, bid=130, outcome="sweep")
        self.assertEqual(result["team2_delta"], 260)
        self.assertEqual(result["team1_delta"], 0)


class WinningThresholdTest(unittest.TestCase):
    def test_exactly_1165_wins(self):
        result = score(team1_score=1045, bid=120, outcome="mak")
        self.assertEqual(result["team1_score"], 1165)
        self.assertEqual(result["winner"], 1)
        self.assertTrue(result["game_finished"])

    def test_1160_does_not_win(self):
        result = score(team1_score=1040, bid=120, outcome="mak")
        self.assertEqual(result["team1_score"], 1160)
        self.assertIsNone(result["winner"])
        self.assertFalse(result["game_finished"])

    def test_score_above_1165_wins(self):
        result = score(team1_score=1164, bid=100, defending_points=50)
        self.assertGreaterEqual(result["team1_score"], 1165)
        self.assertEqual(result["winner"], 1)

    def test_defender_reaches_exactly_1165_on_a_failed_bid(self):
        result = score(team1_score=400, team2_score=1080, bid=120, defending_points=85)
        self.assertEqual(result["team1_score"], 160)
        self.assertEqual(result["team2_score"], 1165)
        self.assertEqual(result["winner"], 2)
        self.assertTrue(result["game_finished"])

    def test_defender_below_1165_does_not_win(self):
        result = score(team1_score=400, team2_score=1075, bid=120, defending_points=85)
        self.assertEqual(result["team2_score"], 1160)
        self.assertIsNone(result["winner"])

    def test_scores_are_not_capped_at_1165(self):
        result = score(team1_score=1100, bid=140, defending_points=25)
        self.assertEqual(result["team1_score"], 1240)

    def test_already_finished_game_is_not_scored(self):
        message = expect_error(
            self,
            {
                "team1_score": 1165,
                "team2_score": 0,
                "bidding_team": 1,
                "bid": 100,
                "defending_points": 0,
            },
            "team1_score",
        )
        self.assertIn("not a new result", message)

    def test_both_already_over_the_threshold_selects_no_winner(self):
        message = expect_error(
            self,
            {
                "team1_score": 1165,
                "team2_score": 1200,
                "bidding_team": 1,
                "bid": 100,
                "defending_points": 0,
            },
            "team1_score",
        )
        self.assertIn("no winner is returned", message)

    def test_unreachable_double_winner_does_not_invent_a_tie_break(self):
        winner, finished, note = ENGINE._winner(1165, 1165)
        self.assertIsNone(winner)
        self.assertFalse(finished)
        self.assertIn("No tie-break", note)


class RegressionTest(unittest.TestCase):
    def test_both_at_1000_hakem_mak_spoken_as_20(self):
        """Spoken "20" is the legal bid 120. Mak is success, not a set.

        Team 2 is defending at 1000, so its 45 captured points are withheld.
        Neither total reaches 1165.
        """
        result = score(
            team1_score=1000,
            team2_score=1000,
            hakem_team=1,
            bidding_team=1,
            bid=120,
            outcome="mak",
        )
        self.assertEqual(
            result,
            {
                "bid": 120,
                "bid_successful": True,
                "bidding_team": 1,
                "contract": "normal",
                "declarer_points": 120,
                "defending_points": 45,
                "defending_team": 2,
                "game_finished": False,
                "hakem_team": 1,
                "scoring_note": None,
                "scoring_rule": "bid_made",
                "team1_delta": 120,
                "team1_score": 1120,
                "team2_delta": 0,
                "team2_score": 1000,
                "thousand_point_rule_applied": True,
                "winner": None,
            },
        )

    def test_raw_abbreviation_20_is_not_scored(self):
        message = expect_error(
            self,
            {
                "team1_score": 1000,
                "team2_score": 1000,
                "hakem_team": 1,
                "bidding_team": 1,
                "bid": 20,
                "outcome": "mak",
            },
            "bid",
        )
        self.assertIn("Abbreviated", message)

    def test_calling_mak_unsuccessful_does_not_produce_a_score(self):
        expect_error(
            self,
            {
                "team1_score": 1000,
                "team2_score": 1000,
                "bidding_team": 1,
                "bid": 120,
                "outcome": "mak",
                "bid_successful": False,
            },
            "bid_successful",
        )


class ValidationTest(unittest.TestCase):
    def test_missing_points(self):
        expect_error(
            self,
            {"team1_score": 0, "team2_score": 0, "bidding_team": 1, "bid": 120},
            "defending_points",
        )

    def test_points_must_sum_to_165(self):
        expect_error(
            self,
            {
                "team1_score": 0,
                "team2_score": 0,
                "bidding_team": 1,
                "bid": 120,
                "defending_points": 40,
                "declarer_points": 120,
            },
            "defending_points",
        )

    def test_non_multiple_of_five_is_unspecified(self):
        for points in (1, 41, 81, 37):
            with self.subTest(points=points):
                message = expect_error(
                    self,
                    {
                        "team1_score": 0,
                        "team2_score": 0,
                        "bidding_team": 1,
                        "bid": 120,
                        "defending_points": points,
                    },
                    "defending_points",
                )
                self.assertIn("multiple of 5", message)

    def test_rejects_floats_booleans_and_strings(self):
        cases = [
            ("team1_score", 10.0, "team1_score"),
            ("team2_score", True, "team2_score"),
            ("bid", "120", "bid"),
            ("defending_points", 25.0, "defending_points"),
        ]
        for field, value, expected_field in cases:
            with self.subTest(field=field):
                payload = {
                    "team1_score": 0,
                    "team2_score": 0,
                    "bidding_team": 1,
                    "bid": 120,
                    "defending_points": 25,
                }
                payload[field] = value
                expect_error(self, payload, expected_field)

    def test_illegal_bids(self):
        for bid in (0, 99, 102, 166, 170, -5):
            with self.subTest(bid=bid):
                expect_error(
                    self,
                    {
                        "team1_score": 0,
                        "team2_score": 0,
                        "bidding_team": 1,
                        "bid": bid,
                        "defending_points": 0,
                    },
                    "bid",
                )

    def test_hakem_and_bidding_team_must_match(self):
        message = expect_error(
            self,
            {
                "team1_score": 0,
                "team2_score": 0,
                "bidding_team": 1,
                "hakem_team": 2,
                "bid": 120,
                "defending_points": 25,
            },
            "hakem_team",
        )
        self.assertIn("do not define", message)

    def test_hakem_alone_is_the_declarer(self):
        result = ENGINE.calculate(
            {
                "team1_score": 0,
                "team2_score": 0,
                "hakem_team": 2,
                "bid": 110,
                "defending_points": 20,
            }
        )
        self.assertEqual(result["bidding_team"], 2)
        self.assertEqual(result["hakem_team"], 2)
        self.assertEqual(result["team2_delta"], 110)

    def test_unknown_field_and_bad_team(self):
        expect_error(
            self,
            {
                "team1_score": 0,
                "team2_score": 0,
                "bidding_team": 1,
                "bid": 120,
                "defending_points": 25,
                "notes": "hello",
            },
            "notes",
        )
        expect_error(
            self,
            {
                "team1_score": 0,
                "team2_score": 0,
                "bidding_team": 3,
                "bid": 120,
                "defending_points": 25,
            },
            "bidding_team",
        )

    def test_negative_cumulative_scores_are_allowed(self):
        result = score(team1_score=-40, team2_score=15, bid=100, defending_points=50)
        self.assertEqual(result["team1_score"], 60)
        self.assertEqual(result["team2_score"], 65)

    def test_out_of_range_points_name_the_supplied_field(self):
        expect_error(
            self,
            {
                "team1_score": 0,
                "team2_score": 0,
                "bidding_team": 1,
                "bid": 120,
                "declarer_points": 170,
            },
            "declarer_points",
        )

    def test_matching_bid_successful_flag_is_accepted(self):
        result = score(bid=135, defending_points=35, bid_successful=False)
        self.assertFalse(result["bid_successful"])

    def test_json_object_is_required(self):
        with self.assertRaises(ENGINE.ScoreInputError):
            ENGINE.calculate([1, 2])

    def test_deltas_reconstruct_the_new_scores(self):
        result = score(team1_score=80, team2_score=-15, bid=125, defending_points=30)
        self.assertEqual(result["team1_score"], 80 + result["team1_delta"])
        self.assertEqual(result["team2_score"], -15 + result["team2_delta"])
        for key in ("team1_delta", "team2_delta", "team1_score", "team2_score"):
            self.assertIs(type(result[key]), int)


REGRESSION_INPUT = {
    "team1_score": 1000,
    "team2_score": 1000,
    "hakem_team": 1,
    "bidding_team": 1,
    "bid": 120,
    "outcome": "mak",
}


class CommandLineTest(unittest.TestCase):
    def _run_main(self, argv, stdin_text):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = ENGINE.main(argv, stdin_text)
        return code, buffer.getvalue()

    def test_main_accepts_valid_json(self):
        code, output = self._run_main([], json.dumps(REGRESSION_INPUT))
        self.assertEqual(code, 0)
        parsed = json.loads(output)
        self.assertEqual(parsed["team1_score"], 1120)
        self.assertEqual(parsed["team2_score"], 1000)
        self.assertIsNone(parsed["winner"])
        self.assertFalse(parsed["game_finished"])

    def test_main_rejects_invalid_json_and_empty_input(self):
        for argv, stdin_text, snippet in (
            ([], "{", "Invalid JSON"),
            ([], "   ", "JSON object"),
            (["one.json", "two.json"], "{}", "one JSON file"),
        ):
            with self.subTest(stdin_text=stdin_text, argv=argv):
                code, output = self._run_main(argv, stdin_text)
                self.assertEqual(code, 1)
                payload = json.loads(output)
                self.assertIn(snippet, payload["error"])
                self.assertNotIn("team1_score", payload)

    def test_subprocess_regression_and_invalid_bid(self):
        env = engine_env()
        valid = subprocess.run(
            ENGINE_COMMAND,
            input=json.dumps(
                {
                    "team1_score": 1000,
                    "team2_score": 1000,
                    "hakem_team": 1,
                    "bidding_team": 1,
                    "bid": 120,
                    "outcome": "mak",
                }
            ).encode("utf-8"),
            capture_output=True,
            cwd=ROOT,
            env=env,
            check=False,
        )
        self.assertEqual(valid.returncode, 0, valid.stderr.decode("utf-8", "replace"))
        self.assertEqual(valid.stderr, b"")
        parsed = json.loads(valid.stdout.decode("utf-8"))
        self.assertEqual(parsed["team1_score"], 1120)
        self.assertEqual(parsed["team2_score"], 1000)
        self.assertIsNone(parsed["winner"])
        self.assertFalse(parsed["game_finished"])

        invalid = subprocess.run(
            ENGINE_COMMAND,
            input=b'{"team1_score": 0, "team2_score": 0, "bidding_team": 1, "bid": 20, "outcome": "mak"}',
            capture_output=True,
            cwd=ROOT,
            env=env,
            check=False,
        )
        self.assertEqual(invalid.returncode, 1)
        error = json.loads(invalid.stdout.decode("utf-8"))
        self.assertEqual(error["field"], "bid")
        self.assertNotIn("team1_score", error)
        self.assertIn("error", error)

    def test_subprocess_reads_a_json_file(self):
        payload = {
            "team1_score": 0,
            "team2_score": 0,
            "bidding_team": 1,
            "bid": 140,
            "defending_points": 25,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hand.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            completed = subprocess.run(
                [*ENGINE_COMMAND, str(path)],
                capture_output=True,
                cwd=ROOT,
                env=engine_env(),
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout.decode("utf-8"))["team1_delta"], 140)


class GameContinuationTest(unittest.TestCase):
    def test_a_game_continues_hand_by_hand_until_one_team_reaches_1165(self):
        hands = [
            dict(bidding_team=1, hakem_team=1, bid=140, defending_points=25),
            dict(bidding_team=2, hakem_team=2, bid=120, defending_points=90),
            dict(bidding_team=1, hakem_team=1, bid=165, contract="shelem", outcome="sweep"),
            dict(bidding_team=1, hakem_team=1, bid=130, outcome="sweep"),
            dict(bidding_team=2, hakem_team=2, bid=150, defending_points=20),
            dict(bidding_team=1, hakem_team=1, bid=120, outcome="mak"),
        ]
        expected = [
            (140, 25, None),
            (230, -215, None),
            (560, -215, None),
            (820, -215, None),
            (840, -365, None),
            (960, -320, None),
        ]
        team1, team2 = 0, 0
        for hand, (want1, want2, want_winner) in zip(hands, expected):
            result = ENGINE.calculate({"team1_score": team1, "team2_score": team2, **hand})
            team1, team2 = result["team1_score"], result["team2_score"]
            self.assertEqual((team1, team2, result["winner"]), (want1, want2, want_winner))
            self.assertFalse(result["game_finished"])

        final = ENGINE.calculate(
            {"team1_score": team1, "team2_score": team2, "bidding_team": 1, "bid": 105, "defending_points": 0}
        )
        self.assertEqual(final["team1_score"], 1170)
        self.assertEqual(final["winner"], 1)
        self.assertTrue(final["game_finished"])


class ExplainTest(unittest.TestCase):
    def test_regression_explanation_names_mak_the_withheld_points_and_continuation(self):
        text = ENGINE.explain(score(team1_score=1000, team2_score=1000, bid=120, outcome="mak"))
        self.assertIn("Mak", text)
        self.assertIn("withheld", text)
        self.assertIn("Team 1 1120, Team 2 1000", text)
        self.assertIn("game continues", text)

    def test_every_scoring_rule_has_a_sentence(self):
        cases = {
            "sweep_double": dict(bid=130, outcome="sweep"),
            "bid_made": dict(bid=120, defending_points=20),
            "bid_failed": dict(bid=135, defending_points=35),
            "heavy_failure": dict(bid=120, defending_points=90),
            "shelem_made": dict(bid=165, contract="shelem", defending_points=0),
            "shelem_failed": dict(bid=165, contract="shelem", defending_points=10),
            "shelem_heavy_failure": dict(bid=165, contract="sare-shelem", defending_points=85),
        }
        for rule, hand in cases.items():
            with self.subTest(rule=rule):
                result = score(**hand)
                self.assertEqual(result["scoring_rule"], rule)
                text = ENGINE.explain(result)
                self.assertIn(f"{result['team1_delta']:+d}", text)
                self.assertIn(f"{result['team2_delta']:+d}", text)

    def test_winner_is_announced_only_when_the_engine_returns_one(self):
        won = ENGINE.explain(score(team1_score=1045, bid=120, outcome="mak"))
        self.assertIn("Team 1 reached 1165 or more and wins", won)
        ongoing = ENGINE.explain(score(team1_score=1040, bid=120, outcome="mak"))
        self.assertNotIn("wins", ongoing)

    def test_explain_does_not_change_the_result(self):
        result = score(team1_score=300, team2_score=1100, bid=140, defending_points=10)
        snapshot = dict(result)
        ENGINE.explain(result)
        self.assertEqual(result, snapshot)


class PortabilityTest(unittest.TestCase):
    def test_engine_uses_only_the_standard_library_and_integers(self):
        modules = set()
        for path in (PACKAGE / "scoring.py", PACKAGE / "rules.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules.add(node.module.split(".")[0])
                elif isinstance(node, ast.Constant) and isinstance(node.value, float):
                    self.fail(f"floating-point constant in {path.name}")
                elif isinstance(node, ast.BinOp) and isinstance(
                    node.op, (ast.Div, ast.FloorDiv)
                ):
                    self.fail(f"division in {path.name}")
        self.assertLessEqual(
            modules, {"__future__", "json", "sys", "pathlib", "typing", "rules"}
        )


class DocumentationContractTest(unittest.TestCase):
    def test_reference_names_the_implemented_rules_and_the_contradiction(self):
        rules = (ROOT / "docs" / "scoring-rules.md").read_text(encoding="utf-8")
        for phrase in (
            "5–40",
            "sweep_double",
            "bid_made",
            "bid_failed",
            "heavy_failure",
            "shelem_made",
            "shelem_failed",
            "shelem_heavy_failure",
            "1165",
            "1000",
            "330",
            "660",
            "src/shelem_mcp/scoring.py",
        ):
            self.assertIn(phrase, rules)


