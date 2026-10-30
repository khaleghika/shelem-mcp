# Shelem Scorekeeping MCP Server

<!-- mcp-name: io.github.khaleghika/shelem-scorekeeping -->

A local [Model Context Protocol](https://modelcontextprotocol.io) server that scores hands of **Shelem (شلم)**, the Persian trick-taking card game. An AI assistant reads the bids and results from conversation, and this server does every score change with deterministic integer arithmetic. The assistant never has to do the maths itself.

The server runs on your machine over STDIO. It has no network access, no database, and no state. It needs nothing hosted.

- PyPI package: [`shelem-scorekeeping-mcp`](https://pypi.org/project/shelem-scorekeeping-mcp/)
- MCP Registry name: `io.github.khaleghika/shelem-scorekeeping` ([registry search](https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.khaleghika/shelem-scorekeeping))
- Source: [github.com/khaleghika/shelem-mcp](https://github.com/khaleghika/shelem-mcp)

## Features

- One tool, `calculate_shelem_score`, with typed input and structured output.
- A scoring engine (`shelem_mcp.scoring`) that is independent of MCP, uses only the Python standard library, and never uses floating point.
- Strict validation. A hand that is missing a fact or contradicts itself returns an error naming the field. The server never guesses a score.
- A plain-English `explanation` of every hand, generated from the engine result.
- Diagnostics are written to stderr only. stdout carries nothing but MCP messages.

## Supported Shelem rules

The full specification, including the contradictions found in the source rules and how each one is resolved, is in [docs/scoring-rules.md](docs/scoring-rules.md). The same document in Persian is [docs/scoring-rules.fa.md](docs/scoring-rules.fa.md).

- Each hand distributes 165 points. Normal bids run from 100 to 165 in steps of 5.
- The Hakem is the declaring team. `hakem_team` and `bidding_team` name the same team.
- **Made bid:** the Hakem captured at least the bid and scores `+bid`. The defenders score what they captured.
- **Mak (مک):** the Hakem captured exactly the bid. This is a made bid, not a failure.
- **Sweep:** the defenders captured nothing, and the Hakem scores `+2 × bid`.
- **Failed bid:** the Hakem captured fewer points than the bid and scores `−bid`. If the defenders captured 85 or more, the Hakem scores `−2 × bid`. The defenders always score what they captured.
- **Shelem / sar-shelem** (a bid of 165 to take every point): `+330` on success, `−330` if the defenders captured 5–80, `−660` if they captured 85 or more. sar-shelem scores the same as Shelem.
- **A normal bid of 165** is scored by the ordinary rules, so the contract must be stated when the bid is 165.
- **1000-point rule:** a *defending* team that was at 1000 or more before the hand scores 0 when the Hakem makes the bid. If the bid fails, it scores what it captured. A team at or above 1000 that is the Hakem is scored normally.
- **Winning:** the game ends when exactly one team reaches **1165** or more. Below that the game continues. Scores are not capped, and negative totals are allowed. No tie-break exists, so the server never invents one.

## Installation

The package name is **`shelem-scorekeeping-mcp`**, and the command it installs has the same name. Python 3.10 or newer is required.

### With uvx (recommended)

[uv](https://docs.astral.sh/uv/) downloads and runs the server in an isolated environment, so there is nothing to install by hand:

```bash
uvx shelem-scorekeeping-mcp --version
```

### With pip

```bash
pip install shelem-scorekeeping-mcp
shelem-scorekeeping-mcp --version
```

`python -m shelem_mcp` also starts the server.

### From a local checkout (before the package is on PyPI)

```bash
git clone https://github.com/khaleghika/shelem-mcp
cd shelem-mcp
uvx --from . shelem-scorekeeping-mcp --version
```

Run without arguments, the command starts the MCP server on STDIO and waits for a client. You do not normally run it yourself. Your MCP client launches it.

Options:

- `--log-level DEBUG|INFO|WARNING|ERROR|CRITICAL` sets the level of diagnostics written to stderr. The default is `WARNING`. The `SHELEM_MCP_LOG_LEVEL` environment variable does the same.
- `--version` prints the version.

## MCP client configuration

### Claude Desktop

Edit `claude_desktop_config.json`. On macOS it is at `~/Library/Application Support/Claude/claude_desktop_config.json`. On Windows it is at `%APPDATA%\Claude\claude_desktop_config.json`.

```json
{
  "mcpServers": {
    "shelem-scorekeeping": {
      "command": "uvx",
      "args": ["shelem-scorekeeping-mcp"]
    }
  }
}
```

Restart Claude Desktop afterwards. If you installed with pip instead, use `"command": "shelem-scorekeeping-mcp"` with `"args": []`.

### Claude Code

```bash
claude mcp add shelem-scorekeeping -- uvx shelem-scorekeeping-mcp
```

Add `--scope user` to make it available in every project. Alternatively, commit a project-level `.mcp.json`:

```json
{
  "mcpServers": {
    "shelem-scorekeeping": {
      "type": "stdio",
      "command": "uvx",
      "args": ["shelem-scorekeeping-mcp"]
    }
  }
}
```

### Cursor and other clients

Any client that launches STDIO servers takes the same `command` and `args`. In Cursor, add the Claude Desktop block above to `~/.cursor/mcp.json` or to `.cursor/mcp.json` in a project.

## Usage

Tell your assistant about the game in your own words, for example: *"We're both on 1000. Team 1 is Hakem, bid 20, and made it exactly (مک)."* The assistant expands the spoken bid "20" to 120 and calls the tool:

```json
{
  "team1_score": 1000,
  "team2_score": 1000,
  "hakem_team": 1,
  "bidding_team": 1,
  "bid": 120,
  "outcome": "mak"
}
```

The server returns this structured result:

```json
{
  "updated_team1_score": 1120,
  "updated_team2_score": 1000,
  "game_finished": false,
  "winner": null,
  "score_changes": {
    "team1": 120,
    "team2": 0
  },
  "explanation": "Team 1 (Hakem) declared a normal bid of 120. Team 1 captured 120 points and Team 2 captured 45. Team 1 captured exactly its bid (Mak), which is a made bid: +120. Team 2 had 1000 before the hand (1000 or more) and the bid was made, so its 45 captured points are withheld: +0. New totals: Team 1 1120, Team 2 1000. Neither team has reached 1165, so the game continues.",
  "hand": {
    "bid": 120,
    "contract": "normal",
    "bidding_team": 1,
    "hakem_team": 1,
    "defending_team": 2,
    "declarer_points": 120,
    "defending_points": 45,
    "bid_successful": true,
    "scoring_rule": "bid_made",
    "thousand_point_rule_applied": true,
    "scoring_note": null
  }
}
```

The server is stateless. The assistant keeps the running totals and passes the totals from before each hand. To correct an earlier hand, it re-scores every hand from that point on.

## Tool reference: `calculate_shelem_score`

### Input

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `team1_score` | integer | yes | Team 1 total before the hand. May be negative. |
| `team2_score` | integer | yes | Team 2 total before the hand. May be negative. |
| `bid` | integer | yes | 100, 105, …, 165. Spoken abbreviations must be expanded first ("20" is 120). |
| `hakem_team` | 1 or 2 | one of the two | The Hakem. |
| `bidding_team` | 1 or 2 | one of the two | The team that won the bidding. Must equal `hakem_team` if both are given. |
| `outcome` | `"mak"` or `"sweep"` | one of the three | `mak`: the Hakem captured exactly the bid. `sweep`: the defenders captured nothing. |
| `defending_points` | integer | one of the three | Points captured by the defenders, 0–165, a multiple of 5. |
| `declarer_points` | integer | one of the three | Points captured by the Hakem. Must sum to 165 with `defending_points`. |
| `contract` | `"normal"`, `"shelem"`, `"sare-shelem"` | when bid is 165 | Omit below 165. |
| `bid_successful` | boolean | no | A cross-check only. If it disagrees with the points, the hand is rejected. |

"One of the two" and "one of the three" mean at least one field from that group is required. When several are given, they must agree.

`bid_successful` alone cannot score a hand. The Hakem's award depends on whether the defenders captured nothing or 85 or more, and the defenders' award is the points they captured. The tool therefore needs the captured points, or `outcome`, as well.

### Output

| Field | Type | Meaning |
| --- | --- | --- |
| `updated_team1_score` | integer | Team 1 total after the hand. |
| `updated_team2_score` | integer | Team 2 total after the hand. |
| `game_finished` | boolean | `true` when exactly one team has reached 1165 or more. |
| `winner` | 1, 2 or `null` | Set only when the game is finished. |
| `score_changes` | `{team1, team2}` | Points each team gained or lost in this hand. |
| `explanation` | string | A plain-English account of the scoring. |
| `hand` | object | Details: the resolved bid, contract, teams, captured points, `bid_successful`, `scoring_rule`, `thousand_point_rule_applied`, `scoring_note`. |

`scoring_rule` is one of `sweep_double`, `bid_made`, `bid_failed`, `heavy_failure`, `shelem_made`, `shelem_failed`, or `shelem_heavy_failure`.

### Errors

Invalid input returns an MCP tool result with `isError: true` and a message that ends in `(field: <name>)`, for example:

```text
bid must be from 100 through 165 in steps of 5. Abbreviated spoken bids are not accepted. (field: bid)
```

No score is returned with an error. The tool refuses to score a hand when either team is already at 1165 or more, because that game is over.

## Using the engine without MCP

```python
from shelem_mcp.scoring import calculate, explain

result = calculate({"team1_score": 0, "team2_score": 0, "bidding_team": 2, "bid": 135, "defending_points": 35})
print(result["team1_score"], result["team2_score"])  # 35 -135
print(explain(result))
```

`python -m shelem_mcp.scoring < hand.json` scores one hand from JSON on the command line.

## Development and testing

```bash
uv venv
uv pip install -e ".[dev]"
uv run pytest
```

The tests cover the following:

- `tests/test_scoring.py` tests the engine alone: every worked example from the source rules, every boundary (999 and 1000, 1160 and 1165, 80 and 85 defensive points), Mak, sweeps, Shelem, validation, a multi-hand game, and the 1000-1000 Mak regression.
- `tests/test_mcp_tools.py` tests the MCP layer: tool discovery and schemas, invocation in-process and over a real STDIO subprocess (both the classic `initialize` handshake and the 2026-07-28 protocol), raw JSON-RPC to check that stdout carries only protocol messages, `server.json` against the official registry schema, and this README's example against the real output.

To build the distribution:

```bash
uv build
uvx twine check dist/*
```

## Publishing

`server.json` uses the current registry schema, `https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json`. It is a local PyPI package on STDIO. There is no remote endpoint. The `mcp-name` comment at the top of this file is the ownership proof PyPI publishing checks.

The current registry guides are:

- [Publish a server](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/quickstart.mdx)
- [GitHub Actions](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/github-actions.mdx)
- [server.json format](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/server-json/generic-server-json.md)
- [Official registry requirements](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/server-json/official-registry-requirements.md)

### GitHub Actions

Pushing a tag such as `v0.1.0` runs [`.github/workflows/publish-mcp.yml`](.github/workflows/publish-mcp.yml). The tag, the package version, and both version fields in `server.json` must be the same number. The workflow tests, builds, publishes `shelem-scorekeeping-mcp` to PyPI with a repository secret named `PYPI_API_TOKEN`, then publishes this repository's `server.json` with `mcp-publisher` v1.8.6. The binary is verified with its Sigstore bundle before it runs, and it authenticates with GitHub OIDC (`login github-oidc`). No registry token is stored in the repository.

Create the PyPI token at [pypi.org/manage/account/token](https://pypi.org/manage/account/token/). Use scope **Entire account** until the project exists, then add it as the GitHub Actions secret `PYPI_API_TOKEN`.

```bash
git tag v0.1.0
git push origin v0.1.0
```

Confirm the release:

```bash
curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.khaleghika/shelem-scorekeeping"
```

### Manual publish

Install `mcp-publisher` from the [quickstart](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/quickstart.mdx), publish the package to PyPI first, then:

```bash
mcp-publisher validate
mcp-publisher login github
mcp-publisher publish
```

`validate` checks `server.json` against the live registry and does not publish it.

## License

MIT. See [LICENSE](LICENSE).
