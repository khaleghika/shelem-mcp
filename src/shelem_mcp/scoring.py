"""Score one Shelem hand.

The normative specification is docs/scoring-rules.md. This module is
stateless and independent of MCP: pass the scores from before the hand and
the hand facts, and it returns the scores after the hand. It uses only the
Python standard library and only integer arithmetic.

It can also be run on its own:

    python -m shelem_mcp.scoring < hand.json

JSON is read from standard input. A single UTF-8 JSON file path may be
given instead.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Mapping, Optional

from .rules import (
    ALLOWED_FIELDS,
    BID_STEP,
    CONTRACTS,
    HAND_TOTAL,
    HEAVY_FAILURE_AT,
    LEGAL_BIDS,
    SHELEM_BID,
    SHELEM_CONTRACTS,
    SHELEM_FAILURE,
    SHELEM_HEAVY_FAILURE,
    SHELEM_SUCCESS,
    THOUSAND_POINT_RULE,
    WIN_THRESHOLD,
)


class ScoreInputError(ValueError):
    """The hand cannot be scored without guessing or breaking a rule."""

    def __init__(self, message: str, field: Optional[str] = None) -> None:
        super().__init__(message)
        self.field = field


def calculate(payload: Mapping[str, object]) -> dict[str, object]:
    """Score one hand and return the JSON-ready result object."""
    if type(payload) is not dict:
        raise ScoreInputError("JSON input must be an object.")

    unknown = sorted(set(payload) - ALLOWED_FIELDS)
    if unknown:
        raise ScoreInputError(f"Unknown field: {unknown[0]}.", field=unknown[0])

    team1 = _integer(payload, "team1_score")
    team2 = _integer(payload, "team2_score")
    _reject_finished_game(team1, team2)

    bidding_team, hakem_team = _teams(payload)
    bid = _bid(payload)
    contract = _contract(payload, bid)
    defending_points = _defending_points(payload, bid)
    declarer_points = HAND_TOTAL - defending_points

    declarer_delta, successful, scoring_rule = _declarer_result(
        bid, defending_points, contract
    )
    _check_reported_success(payload, successful)

    defending_team = 2 if bidding_team == 1 else 1
    defender_score = team1 if defending_team == 1 else team2
    defender_delta, thousand_applied = _defender_result(
        defending_points, successful, defender_score
    )

    if bidding_team == 1:
        team1_delta, team2_delta = declarer_delta, defender_delta
    else:
        team1_delta, team2_delta = defender_delta, declarer_delta

    team1_score = team1 + team1_delta
    team2_score = team2 + team2_delta
    winner, game_finished, scoring_note = _winner(team1_score, team2_score)

    return {
        "bid": bid,
        "bid_successful": successful,
        "bidding_team": bidding_team,
        "contract": contract,
        "declarer_points": declarer_points,
        "defending_points": defending_points,
        "defending_team": defending_team,
        "game_finished": game_finished,
        "hakem_team": hakem_team,
        "scoring_note": scoring_note,
        "scoring_rule": scoring_rule,
        "team1_delta": team1_delta,
        "team1_score": team1_score,
        "team2_delta": team2_delta,
        "team2_score": team2_score,
        "thousand_point_rule_applied": thousand_applied,
        "winner": winner,
    }


def explain(result: Mapping[str, object]) -> str:
    """Describe a result returned by calculate() in plain English.

    The text only restates fields of the result. It never computes a score.
    """
    declarer = result["bidding_team"]
    defender = result["defending_team"]
    bid = result["bid"]
    contract = result["contract"]
    rule = result["scoring_rule"]
    declarer_points = result["declarer_points"]
    defending_points = result["defending_points"]
    deltas = {1: result["team1_delta"], 2: result["team2_delta"]}
    totals = {1: result["team1_score"], 2: result["team2_score"]}
    declarer_delta = f"{deltas[declarer]:+d}"
    defender_delta = f"{deltas[defender]:+d}"

    if contract == "shelem":
        contract_text = "Shelem (165)"
    elif contract == "sare-shelem":
        contract_text = "sar-shelem (165, scored as Shelem)"
    else:
        contract_text = f"a normal bid of {bid}"

    sentences = [
        f"Team {declarer} (Hakem) declared {contract_text}. "
        f"Team {declarer} captured {declarer_points} points and "
        f"Team {defender} captured {defending_points}."
    ]

    if rule == "sweep_double":
        sentences.append(
            f"Team {defender} captured nothing, so Team {declarer} scores "
            f"twice the bid: {declarer_delta}."
        )
    elif rule == "bid_made" and declarer_points == bid:
        sentences.append(
            f"Team {declarer} captured exactly its bid (Mak), which is a made "
            f"bid: {declarer_delta}."
        )
    elif rule == "bid_made":
        sentences.append(
            f"Team {declarer} captured at least its bid, so the bid is made: "
            f"{declarer_delta}."
        )
    elif rule == "bid_failed":
        sentences.append(
            f"Team {declarer} captured fewer points than its bid, so the bid "
            f"failed: {declarer_delta}."
        )
    elif rule == "heavy_failure":
        sentences.append(
            f"Team {declarer} captured fewer points than its bid and Team "
            f"{defender} captured {HEAVY_FAILURE_AT} or more, so the loss is "
            f"doubled: {declarer_delta}."
        )
    elif rule == "shelem_made":
        sentences.append(
            f"Team {declarer} captured every point, so the Shelem is made: "
            f"{declarer_delta}."
        )
    elif rule == "shelem_failed":
        sentences.append(
            f"Team {defender} captured points, so the Shelem failed: "
            f"{declarer_delta}."
        )
    elif rule == "shelem_heavy_failure":
        sentences.append(
            f"Team {defender} captured {HEAVY_FAILURE_AT} or more, so the "
            f"Shelem failed with the heavy penalty: {declarer_delta}."
        )

    if result["thousand_point_rule_applied"]:
        before = totals[defender] - deltas[defender]
        sentences.append(
            f"Team {defender} had {before} before the hand ({THOUSAND_POINT_RULE} "
            f"or more) and the bid was made, so its {defending_points} captured "
            f"points are withheld: {defender_delta}."
        )
    elif defending_points == 0:
        sentences.append(f"Team {defender} captured nothing: {defender_delta}.")
    else:
        sentences.append(
            f"Team {defender} scores the points it captured: {defender_delta}."
        )

    sentences.append(f"New totals: Team 1 {totals[1]}, Team 2 {totals[2]}.")

    winner = result["winner"]
    if winner is not None:
        sentences.append(
            f"Team {winner} reached {WIN_THRESHOLD} or more and wins the game."
        )
    elif result["scoring_note"] is not None:
        sentences.append(str(result["scoring_note"]))
    else:
        sentences.append(
            f"Neither team has reached {WIN_THRESHOLD}, so the game continues."
        )
    return " ".join(sentences)


def _integer(payload: Mapping[str, object], field: str) -> int:
    if field not in payload:
        raise ScoreInputError(f"Missing field: {field}.", field=field)
    return _parse_int(payload[field], field)


def _optional_integer(payload: Mapping[str, object], field: str) -> Optional[int]:
    if field not in payload:
        return None
    return _parse_int(payload[field], field)


def _parse_int(value: object, field: str) -> int:
    if type(value) is bool or type(value) is not int:
        kind = "a boolean" if type(value) is bool else type(value).__name__
        raise ScoreInputError(
            f"{field} must be an integer, not {kind}.",
            field=field,
        )
    return value


def _reject_finished_game(team1: int, team2: int) -> None:
    over1 = team1 >= WIN_THRESHOLD
    over2 = team2 >= WIN_THRESHOLD
    if over1 and over2:
        raise ScoreInputError(
            "Refusing to score this hand because both scores are already "
            "at or above 1165. No tie-break is defined and no winner is returned.",
            field="team1_score",
        )
    if over1 or over2:
        field = "team1_score" if over1 else "team2_score"
        raise ScoreInputError(
            f"Refusing to score this hand because {field} is already at or "
            "above 1165. This is not a new result; do not treat it as a "
            "completed hand.",
            field=field,
        )


def _teams(payload: Mapping[str, object]) -> tuple[int, int]:
    has_bidding = "bidding_team" in payload
    has_hakem = "hakem_team" in payload
    if not has_bidding and not has_hakem:
        raise ScoreInputError(
            "Provide bidding_team or hakem_team. The Hakem is the declarer.",
            field="bidding_team",
        )

    bidding = _team(payload["bidding_team"], "bidding_team") if has_bidding else None
    hakem = _team(payload["hakem_team"], "hakem_team") if has_hakem else None
    if bidding is not None and hakem is not None and bidding != hakem:
        raise ScoreInputError(
            "hakem_team and bidding_team differ. The rules identify the Hakem "
            "as the declarer and do not define scoring when they differ.",
            field="hakem_team",
        )
    declarer = bidding if bidding is not None else hakem
    assert declarer is not None
    return declarer, declarer


def _team(value: object, field: str) -> int:
    team = _parse_int(value, field)
    if team not in (1, 2):
        raise ScoreInputError(f"{field} must be 1 or 2.", field=field)
    return team


def _bid(payload: Mapping[str, object]) -> int:
    bid = _integer(payload, "bid")
    if bid not in LEGAL_BIDS:
        raise ScoreInputError(
            "bid must be from 100 through 165 in steps of 5. "
            "Abbreviated spoken bids are not accepted.",
            field="bid",
        )
    return bid


def _contract(payload: Mapping[str, object], bid: int) -> str:
    if "contract" not in payload:
        if bid == SHELEM_BID:
            raise ScoreInputError(
                "Bid 165 needs contract set to \"shelem\", \"sare-shelem\", "
                "or \"normal\". Shelem failures and a normal bid of 165 are "
                "scored differently, so the contract is not assumed.",
                field="contract",
            )
        return "normal"

    contract = payload["contract"]
    if type(contract) is not str:
        raise ScoreInputError("contract must be a string.", field="contract")
    if contract not in CONTRACTS:
        raise ScoreInputError(
            "contract must be \"normal\", \"shelem\", or \"sare-shelem\".",
            field="contract",
        )
    if contract in SHELEM_CONTRACTS and bid != SHELEM_BID:
        raise ScoreInputError(
            f"contract {contract} is scored as 165, but bid is {bid}.",
            field="contract",
        )
    return contract


def _defending_points(payload: Mapping[str, object], bid: int) -> int:
    implied = _outcome_points(payload, bid)
    supplied_defending = "defending_points" in payload
    supplied_declarer = "declarer_points" in payload
    defending = _optional_integer(payload, "defending_points")
    declarer = _optional_integer(payload, "declarer_points")

    if not supplied_defending and not supplied_declarer and implied is None:
        raise ScoreInputError(
            "Provide defending_points, declarer_points, or outcome "
            "(\"mak\" or \"sweep\").",
            field="defending_points",
        )
    if supplied_defending:
        assert defending is not None
        _validate_points(defending, "defending_points")
    if supplied_declarer:
        assert declarer is not None
        _validate_points(declarer, "declarer_points")
    if (
        supplied_defending
        and supplied_declarer
        and defending + declarer != HAND_TOTAL
    ):
        raise ScoreInputError(
            f"defending_points and declarer_points must add up to {HAND_TOTAL}.",
            field="defending_points",
        )
    if not supplied_defending and supplied_declarer:
        assert declarer is not None
        defending = HAND_TOTAL - declarer
    if defending is None:
        assert implied is not None
        defending = implied
    elif implied is not None and defending != implied:
        raise ScoreInputError(
            "outcome conflicts with the reported points.",
            field="outcome",
        )
    _validate_points(defending, "defending_points")
    return defending


def _outcome_points(payload: Mapping[str, object], bid: int) -> Optional[int]:
    if "outcome" not in payload:
        return None
    outcome = payload["outcome"]
    if type(outcome) is not str:
        raise ScoreInputError("outcome must be a string.", field="outcome")
    if outcome == "mak":
        return HAND_TOTAL - bid
    if outcome == "sweep":
        return 0
    raise ScoreInputError(
        "outcome must be \"mak\" or \"sweep\".",
        field="outcome",
    )


def _validate_points(value: int, field: str) -> None:
    if value < 0 or value > HAND_TOTAL:
        raise ScoreInputError(
            f"{field} must be from 0 through {HAND_TOTAL}.",
            field=field,
        )
    if value % BID_STEP != 0:
        raise ScoreInputError(
            f"{field} must be a multiple of 5. Totals that are not multiples "
            "of 5 are not specified by the scoring tables.",
            field=field,
        )


def _declarer_result(
    bid: int, defending_points: int, contract: str
) -> tuple[int, bool, str]:
    if contract in SHELEM_CONTRACTS:
        if defending_points == 0:
            return SHELEM_SUCCESS, True, "shelem_made"
        if defending_points >= HEAVY_FAILURE_AT:
            return SHELEM_HEAVY_FAILURE, False, "shelem_heavy_failure"
        return SHELEM_FAILURE, False, "shelem_failed"

    if defending_points == 0:
        return 2 * bid, True, "sweep_double"
    declarer_points = HAND_TOTAL - defending_points
    if declarer_points >= bid:
        return bid, True, "bid_made"
    if defending_points >= HEAVY_FAILURE_AT:
        return -2 * bid, False, "heavy_failure"
    return -bid, False, "bid_failed"


def _check_reported_success(payload: Mapping[str, object], successful: bool) -> None:
    if "bid_successful" not in payload:
        return
    reported = payload["bid_successful"]
    if type(reported) is not bool:
        raise ScoreInputError(
            "bid_successful must be a boolean.",
            field="bid_successful",
        )
    if reported != successful:
        actual = "successful" if successful else "unsuccessful"
        raise ScoreInputError(
            "bid_successful does not match the captured points "
            f"(the bid is {actual}). The points are left unchanged.",
            field="bid_successful",
        )


def _defender_result(
    defending_points: int, successful: bool, defender_score: int
) -> tuple[int, bool]:
    ordinary = 0 if defending_points == 0 else defending_points
    if (
        successful
        and defender_score >= THOUSAND_POINT_RULE
        and ordinary != 0
    ):
        return 0, True
    return ordinary, False


def _winner(
    team1_score: int, team2_score: int
) -> tuple[Optional[int], bool, Optional[str]]:
    over1 = team1_score >= WIN_THRESHOLD
    over2 = team2_score >= WIN_THRESHOLD
    if over1 and over2:
        return (
            None,
            False,
            "Both teams reached 1165. No tie-break is defined, so no winner is returned.",
        )
    if over1:
        return 1, True, None
    if over2:
        return 2, True, None
    return None, False, None


def read_input(argv: list[str], stdin_text: Optional[str]) -> str:
    if len(argv) > 1:
        raise ScoreInputError(
            "Pass JSON on standard input, or pass one JSON file path.",
        )
    if len(argv) == 1:
        path = Path(argv[0])
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ScoreInputError(f"Could not read {path}: {exc.strerror}.") from exc
    if stdin_text is None:
        stdin_text = sys.stdin.read()
    return stdin_text


def main(argv: Optional[list[str]] = None, stdin_text: Optional[str] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    try:
        raw = read_input(argv, stdin_text)
        if raw.strip() == "":
            raise ScoreInputError("Expected a JSON object on standard input.")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ScoreInputError(f"Invalid JSON: {exc.msg}.") from exc
        result = calculate(payload)
    except ScoreInputError as exc:
        _emit({"error": str(exc), "field": exc.field})
        return 1
    _emit(result)
    return 0


def _emit(payload: Mapping[str, object]) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    sys.exit(main())
