"""Shelem rule constants.

docs/scoring-rules.md is the specification these values come from. The
scoring engine in scoring.py is the only code that applies them.
"""

from __future__ import annotations

HAND_TOTAL = 165
WIN_THRESHOLD = 1165
THOUSAND_POINT_RULE = 1000
HEAVY_FAILURE_AT = 85
MIN_BID = 100
BID_STEP = 5
SHELEM_BID = 165
SHELEM_SUCCESS = 330
SHELEM_FAILURE = -330
SHELEM_HEAVY_FAILURE = -660

LEGAL_BIDS = frozenset(range(MIN_BID, SHELEM_BID + 1, BID_STEP))
CONTRACTS = ("normal", "shelem", "sare-shelem")
SHELEM_CONTRACTS = frozenset({"shelem", "sare-shelem"})
OUTCOMES = ("mak", "sweep")
SUCCESSFUL_RULES = frozenset({"sweep_double", "bid_made", "shelem_made"})

ALLOWED_FIELDS = frozenset(
    {
        "team1_score",
        "team2_score",
        "hakem_team",
        "bidding_team",
        "bid",
        "contract",
        "defending_points",
        "declarer_points",
        "outcome",
        "bid_successful",
    }
)
