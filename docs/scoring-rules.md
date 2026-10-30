# Shelem scoring rules

Persian: [scoring-rules.fa.md](scoring-rules.fa.md).

`src/shelem_mcp/scoring.py` is the scoring authority. This file records the source rules, the contradictions in those rules, and the procedure the engine implements. Do not score a hand from this file. If this file and the engine ever disagree, the engine and `tests/test_scoring.py` win. In the sections below, "the script" means that engine; the MCP tool `calculate_shelem_score` calls it and adds no scoring logic of its own.

The script scores one hand. It does not remember earlier hands, interpret speech, or choose a winner that the rules do not define.

## Source rules

These statements are copied from the original skill. They remain the source text. The next section says where they conflict.

Shelem is played by two teams. The game ends when one team reaches or exceeds 1165. Each hand distributes 165 points between the teams. Only one team can reach the winning threshold. The source forbids adding a tie-break.

Normal bids start at 100, increase by 5, and stop at 165. Shelem is a bid of 165. sar-shelem is bid only after a Shelem bid, but its scoring is the same as Shelem. A successful Shelem or sar-shelem requires the defending team to capture exactly zero points.

For a normal hand, `B` is the bid and `D` is the points captured by the defending team. The Hakem's team captured `C = 165 - D`. The original skill gives this table:

| Defending team's points (D) | Hakem's team | Defending team |
| --- | ---: | ---: |
| 0 | +2 × B | 0 |
| 5–40 | +B | +D |
| 45–80 | −B | +D |
| 85–165 | −2 × B | +D |

Worked normal hands in the source:

- Bid 140, defenders 25, Hakem 140: Hakem +140, defenders +25.
- Bid 135, defenders 35, Hakem 130: Hakem −135, defenders +35. The source calls this a failed bid because 130 is below 135.
- Bid 140, defenders 10: Hakem +140, defenders +10.
- Bid 120, defenders 90: Hakem −240, defenders +90.

Mak means the Hakem's team captured exactly the bid. It is not a failed bid. The source's Mak example is bid 140, defenders 25, Hakem 140: Hakem +140, defenders +25, subject to the 1000-point rule.

Capturing every point is not the same thing as bidding Shelem. For a bid of 130 with defenders on zero, the source awards the Hakem +260 and the defenders 0.

The Shelem table is:

| Defending team's points | Hakem's team | Defending team |
| --- | ---: | ---: |
| 0 | +330 | 0 |
| 5–80 | −330 | +D |
| 85 or more | −660 | +D |

The 1000-point rule uses the scores from before the hand and applies separately to each team.

- A team at or above 1000 that is the Hakem is scored by the ordinary Hakem rules. Nothing about its own score changes those rules.
- A team at or above 1000 that is defending scores 0 if the Hakem makes the bid, whatever that team captured. If the Hakem fails, that team scores the points it actually captured.
- The Hakem's award is not changed by this rule.

Source examples of that rule:

- Defenders are on 1100 and capture 10 against a bid of 140. The Hakem makes the bid. Defenders get 0, not +10. Hakem gets +140.
- Defenders are on 1100 and capture 35 against a bid of 140. The Hakem captured 130 and fails. Defenders get +35. Hakem gets −140.
- The team on 1100 is the Hakem and bids 140. The defenders capture 25. Hakem gets +140 and defenders get +25.

In the first of those examples the source writes the defender's result as `0`. That is a zero award for the hand, not a reset of the team's cumulative score.

After the hand, a team at or above 1165 wins. The source does not cap the score at 1165.

## Contradictions and unspecified cases

The script does not paper over these. Each item says what the script does instead of guessing.

1. **The fixed bands contradict the worked hands.** The table awards `+B` for every defensive total from 5 through 40 and `−B` for every total from 45 through 80. The bid-135 hand has a defensive total of 35 and is scored `−B` in the source, because the Hakem captured 130, which is short of 135. The same failure rule is repeated for a bid of 140 with 35 defensive points. Mak at a bid of 120 has 45 defensive points and is a made bid, so the 45–80 band would score it as a failure. The script follows the worked hands and the Mak rule: compare the Hakem's captured points with the bid. It keeps the table's two cases that those hands do not contradict: defenders on zero doubles the Hakem's award, and a failed bid with defenders on 85 or more doubles the loss.

2. **A bid of 165 is both the maximum normal bid and a Shelem.** The Shelem failure awards, −330 and −660, are twice the awards the general failure rule gives a bid of 165, −165 and −330. Success is +330 either way, because the only successful 165 is a sweep. The script refuses a bid of 165 unless `contract` is `shelem`, `sare-shelem`, or `normal`.

3. **sar-shelem has no scoring difference.** The script accepts `sare-shelem` and scores it with the Shelem table. It does not check that a Shelem bid came first, and it does not represent the rule that the sar-shelem Hakem cannot exchange the four table cards. Those are playing constraints, not a second score.

4. **In the source, the bidding team is the Hakem.** If `hakem_team` and `bidding_team` are both present and different, the script rejects the hand. It does not pick one.

5. **Both teams at or above 1165.** The source says this does not happen and that no tie-break should be invented. A hand that starts in that state is rejected and no winner is returned. A result that somehow ended that way would return `winner: null`, `game_finished: false`, and a `scoring_note`. Legal awards cannot finish a hand that way: the Hakem gains points only when the bid is made, and a defender who is close enough to reach 1165 is already at or above 1000, so a made bid withholds that defender's points.

6. **Point totals that are not multiples of 5.** Every source boundary and example is a multiple of 5. The gaps 1–4, 41–44, and 81–84 are inside none of the written bands, and a Shelem total of 81 through 84 is in neither Shelem row. The script rejects any captured total that is not a multiple of 5 from 0 through 165.

7. **Spoken abbreviations are not bids.** "20" in speech can mean 120, just as the source says "40" can mean 140. The script accepts only 100, 105, …, 165. The 1000/1000 Mak regression is bid 120, not bid 20. A payload with `bid: 20` and `bid_successful: false` is invalid, and it is not that hand: Mak is a made bid.

8. **A zero defensive award does not wipe the cumulative score.** The team keeps the score it had before the hand.

9. **Scores are not capped, and negative scores are allowed.** The source says "or exceeds" and "or more." A failed bid can push a total below zero. The script accepts a negative opening score on a later hand.

10. **`bid_successful` does not choose the award.** Captured points do. If the flag is present and disagrees, the script returns an error and does not emit a new score.

11. **`bid_successful` alone cannot score a hand.** A made bid can be `+B` or `+2 × B`, and a failed bid can be `−B` or `−2 × B`. The defenders are awarded the points they actually captured. None of that is determined by a yes/no flag, so the MCP tool also requires `defending_points`, `declarer_points`, or `outcome`. The flag stays available as a cross-check.

## Procedure implemented by the script

All arithmetic is integer arithmetic.

1. Reject a non-object, an unknown field, a missing score or bid, or any value that is not an integer. Booleans and fractional numbers are rejected. Teams must be 1 or 2.
2. If either opening score is 1165 or more, refuse the hand. If both are, say that no tie-break exists and do not name a winner.
3. Resolve the Hakem. Use `bidding_team`, `hakem_team`, or both when they agree.
4. Accept a bid only when it is one of 100, 105, …, 165.
5. Resolve the contract. Omit `contract` on a bid below 165 and the contract is `normal`. A bid of 165 must name `normal`, `shelem`, or `sare-shelem`. A Shelem contract on any other bid is rejected.
6. Resolve `D`. `outcome: "mak"` means the Hakem captured exactly the bid, so `D = 165 - bid`. `outcome: "sweep"` means `D = 0`. Otherwise take `defending_points`, or derive it from `declarer_points`. When more than one of these is present, they must agree, and the two point fields must sum to 165. `D` must be an integer multiple of 5 from 0 through 165. `C = 165 - D`.
7. Award the Hakem:

| `scoring_rule` | Contract | Condition | Hakem |
| --- | --- | --- | ---: |
| `sweep_double` | normal | `D = 0` | `+2 × bid` |
| `bid_made` | normal | `D > 0` and `C >= bid` | `+bid` |
| `bid_failed` | normal | `C < bid` and `D < 85` | `−bid` |
| `heavy_failure` | normal | `C < bid` and `D >= 85` | `−2 × bid` |
| `shelem_made` | shelem or sare-shelem | `D = 0` | +330 |
| `shelem_failed` | shelem or sare-shelem | `D` is 5, 10, …, 80 | −330 |
| `shelem_heavy_failure` | shelem or sare-shelem | `D >= 85` | −660 |

   The bid is successful only for `sweep_double`, `bid_made`, and `shelem_made`.

8. Award the defending team its captured points, except when the bid succeeded and that team's score before the hand is 1000 or more. Then its award is 0. `thousand_point_rule_applied` is true only when this exception removes a nonzero award. A sweep already awards the defenders 0, so the flag stays false.
9. Add each award to the matching team's opening score.
10. If exactly one new score is 1165 or more, that team is `winner` and `game_finished` is true. Otherwise `winner` is null and `game_finished` is false.

## Results the script must reproduce

| Hand | Hakem | Defender |
| --- | ---: | ---: |
| Normal bid 140, D = 25 | +140 | +25 |
| Normal bid 135, D = 35 | −135 | +35 |
| Normal bid 140, D = 10 | +140 | +10 |
| Normal bid 120, D = 90 | −240 | +90 |
| Mak at 140 | +140 | +25 |
| Sweep at bid 130 | +260 | 0 |
| Shelem, D = 0 | +330 | 0 |
| Shelem, D = 5 through 80 | −330 | +D |
| Shelem, D = 85 or more | −660 | +D |
| sar-shelem, same D | same as Shelem | same as Shelem |
| Normal bid 165, D = 10 | −165 | +10 |
| Normal bid 165, D = 85 | −330 | +85 |
| Defenders on 1100, opposing bid 140, D = 10 | Hakem +140 | 0 |
| Defenders on 1100, opposing bid 140, D = 35 | Hakem −140 | +35 |
| Hakem on 1100, bid 140, D = 25 | +140 | +25 |
| Both teams on 1000, team 1 declares Mak at 120 | team 1 +120, total 1120 | team 2 +0, total 1000, no winner |

The last row is the regression hand. Spoken "20" has already been expanded to 120. Team 2 captured 45 and was already on 1000, and the bid was made, so those 45 points are withheld. 1120 is below 1165, so the game continues.
