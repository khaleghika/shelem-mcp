"""MCP server exposing the Shelem scoring engine over STDIO.

stdout carries MCP protocol messages only. All diagnostics go to stderr.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Annotated, Literal, Optional

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from . import __version__, scoring

logger = logging.getLogger("shelem_mcp")

SERVER_NAME = "shelem-scorekeeping"

INSTRUCTIONS = """\
Scores Shelem (شلم) hands. The server is stateless: keep the running game \
state yourself and pass the totals from before each hand.

- Call calculate_shelem_score once per completed hand. Never compute a \
score yourself and never announce a winner the tool did not return.
- Expand spoken abbreviated bids before calling: "20" means 120, "40" \
means 140. Only 100, 105, ..., 165 are legal bids.
- Mak (مک) means the declarer captured exactly the bid; send outcome="mak".
- A bid of 165 needs contract "shelem", "sare-shelem" or "normal".
- If the tool returns an error, ask the user for the missing or \
contradictory fact instead of changing the numbers.
- To correct an earlier hand, re-score every hand from that point on.
"""

TOOL_DESCRIPTION = """\
Score one completed Shelem hand and return both teams' new totals.

Pass the cumulative scores from before the hand, the declaring team, the \
bid, and how many points were captured (defending_points, declarer_points, \
or outcome "mak"/"sweep"). The engine applies the doubled sweep award, \
failed and heavily failed bids, Shelem/sar-shelem (+330/-330/-660), the \
1000-point rule for a defending team, and the 1165 winning threshold. All \
arithmetic is integer and deterministic.

Invalid or contradictory input returns an error and no score.
"""

class ScoreChanges(BaseModel):
    team1: int = Field(description="Points Team 1 gained or lost this hand.")
    team2: int = Field(description="Points Team 2 gained or lost this hand.")


class HandDetails(BaseModel):
    bid: int = Field(description="The legal bid that was scored.")
    contract: Literal["normal", "shelem", "sare-shelem"]
    bidding_team: int = Field(description="The declaring team (the Hakem).")
    hakem_team: int = Field(description="Same as bidding_team.")
    defending_team: int
    declarer_points: int = Field(description="Points captured by the declarer.")
    defending_points: int = Field(description="Points captured by the defenders.")
    bid_successful: bool = Field(description="True when the bid was made. Mak is a made bid.")
    scoring_rule: Literal[
        "sweep_double",
        "bid_made",
        "bid_failed",
        "heavy_failure",
        "shelem_made",
        "shelem_failed",
        "shelem_heavy_failure",
    ] = Field(description="The declarer rule that was applied.")
    thousand_point_rule_applied: bool = Field(
        description=(
            "True when the defending team was at 1000 or more before the hand, "
            "the bid was made, and its captured points were withheld."
        )
    )
    scoring_note: Optional[str] = Field(
        description="Set only when the rules cannot name a winner."
    )


class ShelemScoreResult(BaseModel):
    updated_team1_score: int = Field(description="Team 1 total after the hand.")
    updated_team2_score: int = Field(description="Team 2 total after the hand.")
    game_finished: bool = Field(description="True when exactly one team reached 1165 or more.")
    winner: Optional[int] = Field(description="1 or 2 when the game is finished, otherwise null.")
    score_changes: ScoreChanges
    explanation: str = Field(description="Plain-English account of how the hand was scored.")
    hand: HandDetails


def build_server() -> MCPServer:
    server = MCPServer(
        name=SERVER_NAME,
        title="Shelem Scorekeeping",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url="https://github.com/khaleghika/shelem-mcp",
    )

    @server.tool(
        name="calculate_shelem_score",
        title="Calculate Shelem score",
        description=TOOL_DESCRIPTION,
        annotations=ToolAnnotations(
            title="Calculate Shelem score",
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def calculate_shelem_score(
        team1_score: Annotated[
            int,
            Field(strict=True, description="Team 1 cumulative score before this hand. May be negative."),
        ],
        team2_score: Annotated[
            int,
            Field(strict=True, description="Team 2 cumulative score before this hand. May be negative."),
        ],
        bid: Annotated[
            int,
            Field(
                strict=True,
                description=(
                    "The winning bid: 100, 105, ..., 165. Expand spoken "
                    "abbreviations first (\"20\" is 120)."
                ),
            ),
        ],
        hakem_team: Annotated[
            Optional[int],
            Field(strict=True, description="Team of the Hakem (the declarer): 1 or 2."),
        ] = None,
        bidding_team: Annotated[
            Optional[int],
            Field(
                strict=True,
                description=(
                    "Team that won the bidding: 1 or 2. Must equal hakem_team "
                    "when both are given. At least one of the two is required."
                ),
            ),
        ] = None,
        bid_successful: Annotated[
            Optional[bool],
            Field(
                strict=True,
                description=(
                    "Optional cross-check. The captured points decide success; "
                    "if this flag disagrees the hand is rejected. Mak is successful."
                ),
            ),
        ] = None,
        outcome: Annotated[
            Optional[Literal["mak", "sweep"]],
            Field(
                description=(
                    "\"mak\": the declarer captured exactly the bid. "
                    "\"sweep\": the defenders captured nothing. "
                    "Use instead of, or consistently with, the point fields."
                )
            ),
        ] = None,
        defending_points: Annotated[
            Optional[int],
            Field(
                strict=True,
                description="Points captured by the defending team: 0-165, multiple of 5.",
            ),
        ] = None,
        declarer_points: Annotated[
            Optional[int],
            Field(
                strict=True,
                description=(
                    "Points captured by the declaring team: 0-165, multiple of 5. "
                    "Must sum to 165 with defending_points when both are given."
                ),
            ),
        ] = None,
        contract: Annotated[
            Optional[Literal["normal", "shelem", "sare-shelem"]],
            Field(
                description=(
                    "Omit below 165. Required when bid is 165: \"shelem\", "
                    "\"sare-shelem\" or \"normal\" (scored differently on failure)."
                )
            ),
        ] = None,
    ) -> ShelemScoreResult:
        supplied = {
            "team1_score": team1_score,
            "team2_score": team2_score,
            "bid": bid,
            "hakem_team": hakem_team,
            "bidding_team": bidding_team,
            "bid_successful": bid_successful,
            "outcome": outcome,
            "defending_points": defending_points,
            "declarer_points": declarer_points,
            "contract": contract,
        }
        payload = {key: value for key, value in supplied.items() if value is not None}
        try:
            result = scoring.calculate(payload)
        except scoring.ScoreInputError as exc:
            field = f" (field: {exc.field})" if exc.field else ""
            raise ToolError(f"{exc}{field}") from exc
        return to_tool_result(result)

    return server


def to_tool_result(result: dict[str, object]) -> ShelemScoreResult:
    return ShelemScoreResult(
        updated_team1_score=result["team1_score"],
        updated_team2_score=result["team2_score"],
        game_finished=result["game_finished"],
        winner=result["winner"],
        score_changes=ScoreChanges(team1=result["team1_delta"], team2=result["team2_delta"]),
        explanation=scoring.explain(result),
        hand=HandDetails(
            bid=result["bid"],
            contract=result["contract"],
            bidding_team=result["bidding_team"],
            hakem_team=result["hakem_team"],
            defending_team=result["defending_team"],
            declarer_points=result["declarer_points"],
            defending_points=result["defending_points"],
            bid_successful=result["bid_successful"],
            scoring_rule=result["scoring_rule"],
            thousand_point_rule_applied=result["thousand_point_rule_applied"],
            scoring_note=result["scoring_note"],
        ),
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="shelem-scorekeeping-mcp",
        description="Shelem scorekeeping MCP server (STDIO transport).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--log-level",
        default=os.environ.get("SHELEM_MCP_LOG_LEVEL", "WARNING"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Log level for diagnostics written to stderr (default: WARNING).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        stream=sys.stderr,
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("Starting %s %s on stdio", SERVER_NAME, __version__)
    build_server().run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
