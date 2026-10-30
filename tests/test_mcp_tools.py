"""Tests for the MCP layer: discovery, invocation, STDIO framing and metadata."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import unittest
from pathlib import Path

import jsonschema
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from shelem_mcp import __version__, scoring
from shelem_mcp.server import build_server

ROOT = Path(__file__).resolve().parents[1]
SERVER_JSON = ROOT / "server.json"
REGISTRY_SCHEMA = ROOT / "tests" / "schemas" / "server.schema.2025-12-11.json"
TOOL = "calculate_shelem_score"

REGRESSION_ARGS = {
    "team1_score": 1000,
    "team2_score": 1000,
    "hakem_team": 1,
    "bidding_team": 1,
    "bid": 120,
    "outcome": "mak",
}


def server_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(ROOT / "src"), env.get("PYTHONPATH")])
    )
    return env


def stdio_params(*extra: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "shelem_mcp", *extra],
        env=server_env(),
        cwd=str(ROOT),
    )


def check_regression(testcase: unittest.TestCase, structured: dict) -> None:
    testcase.assertEqual(structured["updated_team1_score"], 1120)
    testcase.assertEqual(structured["updated_team2_score"], 1000)
    testcase.assertIsNone(structured["winner"])
    testcase.assertFalse(structured["game_finished"])
    testcase.assertEqual(structured["score_changes"], {"team1": 120, "team2": 0})
    testcase.assertTrue(structured["hand"]["thousand_point_rule_applied"])
    testcase.assertEqual(structured["hand"]["scoring_rule"], "bid_made")
    testcase.assertIn("Mak", structured["explanation"])


class _InProcessClient:
    async def list_tools(self):
        async with Client(build_server()) as client:
            return await client.list_tools()

    async def call_tool(self, name, arguments):
        async with Client(build_server()) as client:
            return await client.call_tool(name, arguments)


class InProcessToolTest(unittest.IsolatedAsyncioTestCase):
    client = _InProcessClient()

    async def test_discovery_lists_one_typed_tool(self):
        tools = (await self.client.list_tools()).tools
        self.assertEqual([tool.name for tool in tools], [TOOL])
        tool = tools[0]
        schema = tool.input_schema
        self.assertEqual(set(schema["required"]), {"team1_score", "team2_score", "bid"})
        for field in (
            "team1_score",
            "team2_score",
            "hakem_team",
            "bidding_team",
            "bid",
            "bid_successful",
            "outcome",
            "defending_points",
            "declarer_points",
            "contract",
        ):
            self.assertIn(field, schema["properties"])
            self.assertTrue(schema["properties"][field].get("description"))
        output = tool.output_schema
        for field in (
            "updated_team1_score",
            "updated_team2_score",
            "game_finished",
            "winner",
            "score_changes",
            "explanation",
        ):
            self.assertIn(field, output["properties"])
        self.assertTrue(tool.annotations.read_only_hint)
        self.assertTrue(tool.annotations.idempotent_hint)
        self.assertFalse(tool.annotations.open_world_hint)

    async def test_regression_1000_1000_hakem_mak_at_120(self):
        result = await self.client.call_tool(TOOL, REGRESSION_ARGS)
        self.assertFalse(result.is_error)
        check_regression(self, result.structured_content)
        text = json.loads(result.content[0].text)
        self.assertEqual(text, result.structured_content)

    async def test_tool_returns_exactly_what_the_engine_returns(self):
        cases = [
            dict(team1_score=0, team2_score=0, bidding_team=2, bid=135, defending_points=35),
            dict(team1_score=400, team2_score=1080, hakem_team=1, bid=120, defending_points=85),
            dict(team1_score=100, team2_score=1100, hakem_team=1, bid=165, contract="shelem", defending_points=10),
            dict(team1_score=-40, team2_score=15, bidding_team=1, bid=100, declarer_points=115),
        ]
        for args in cases:
            with self.subTest(args=args):
                engine = scoring.calculate(dict(args))
                result = await self.client.call_tool(TOOL, args)
                self.assertFalse(result.is_error)
                got = result.structured_content
                self.assertEqual(got["updated_team1_score"], engine["team1_score"])
                self.assertEqual(got["updated_team2_score"], engine["team2_score"])
                self.assertEqual(got["winner"], engine["winner"])
                self.assertEqual(got["game_finished"], engine["game_finished"])
                self.assertEqual(
                    got["score_changes"],
                    {"team1": engine["team1_delta"], "team2": engine["team2_delta"]},
                )
                self.assertEqual(got["explanation"], scoring.explain(engine))

    async def test_winner_is_returned_when_1165_is_reached(self):
        result = await self.client.call_tool(
            TOOL,
            {"team1_score": 400, "team2_score": 1080, "hakem_team": 1, "bid": 120, "defending_points": 85},
        )
        self.assertEqual(result.structured_content["winner"], 2)
        self.assertTrue(result.structured_content["game_finished"])

    async def test_abbreviated_bid_20_is_an_error_not_a_score(self):
        args = dict(REGRESSION_ARGS, bid=20)
        result = await self.client.call_tool(TOOL, args)
        self.assertTrue(result.is_error)
        self.assertIsNone(result.structured_content)
        message = result.content[0].text
        self.assertIn("Abbreviated", message)
        self.assertIn("field: bid", message)

    async def test_engine_validation_errors_are_reported(self):
        cases = {
            "bid_successful": dict(REGRESSION_ARGS, bid_successful=False),
            "hakem_team": dict(REGRESSION_ARGS, bidding_team=2),
            "contract": dict(REGRESSION_ARGS, bid=165, outcome="sweep"),
            "defending_points": {k: v for k, v in REGRESSION_ARGS.items() if k != "outcome"},
            "team1_score": dict(REGRESSION_ARGS, team1_score=1165),
        }
        for field, args in cases.items():
            with self.subTest(field=field):
                result = await self.client.call_tool(TOOL, args)
                self.assertTrue(result.is_error)
                self.assertIn(f"field: {field}", result.content[0].text)

    async def test_schema_type_errors_are_rejected(self):
        for args in (
            dict(REGRESSION_ARGS, bid=120.5),
            dict(REGRESSION_ARGS, team1_score=True),
            dict(REGRESSION_ARGS, outcome="set"),
            {"team2_score": 0, "bid": 120, "bidding_team": 1, "outcome": "mak"},
        ):
            with self.subTest(args=args):
                result = await self.client.call_tool(TOOL, args)
                self.assertTrue(result.is_error)


class StdioServerTest(unittest.IsolatedAsyncioTestCase):
    async def _exercise(self, mode: str) -> None:
        async with Client(stdio_params(), mode=mode, read_timeout_seconds=60) as client:
            tools = (await client.list_tools()).tools
            self.assertEqual([tool.name for tool in tools], [TOOL])
            result = await client.call_tool(TOOL, REGRESSION_ARGS)
            self.assertFalse(result.is_error)
            check_regression(self, result.structured_content)

    async def test_modern_protocol_over_stdio(self):
        await self._exercise("auto")

    async def test_legacy_initialize_handshake_over_stdio(self):
        await self._exercise("legacy")


class RawStdoutTest(unittest.TestCase):
    """Drive the server with hand-written JSON-RPC and inspect every stdout line."""

    def test_stdout_carries_only_json_rpc_and_logs_go_to_stderr(self):
        process = subprocess.Popen(
            [sys.executable, "-m", "shelem_mcp", "--log-level", "DEBUG"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=ROOT,
            env=server_env(),
        )
        watchdog = threading.Timer(60, process.kill)
        watchdog.start()
        stderr_chunks: list[bytes] = []
        reader = threading.Thread(target=lambda: stderr_chunks.append(process.stderr.read()))
        reader.start()
        responses = {}
        try:
            def send(message: dict) -> None:
                process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
                process.stdin.flush()

            def receive(request_id: int) -> dict:
                while True:
                    line = process.stdout.readline()
                    self.assertTrue(line, "server closed stdout early")
                    message = json.loads(line.decode("utf-8"))
                    self.assertEqual(message["jsonrpc"], "2.0")
                    if message.get("id") == request_id:
                        return message

            send({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "raw-test", "version": "0"},
                },
            })
            responses["initialize"] = receive(1)
            send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            responses["list"] = receive(2)
            send({
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": TOOL, "arguments": REGRESSION_ARGS},
            })
            responses["call"] = receive(3)
            send({
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": TOOL, "arguments": dict(REGRESSION_ARGS, bid=20)},
            })
            responses["error"] = receive(4)
            process.stdin.close()
            leftover = process.stdout.read()
            process.wait(timeout=30)
        finally:
            watchdog.cancel()
            if process.poll() is None:
                process.kill()
            reader.join(timeout=10)

        for line in leftover.decode("utf-8").splitlines():
            if line.strip():
                self.assertEqual(json.loads(line)["jsonrpc"], "2.0")

        init = responses["initialize"]["result"]
        self.assertEqual(init["serverInfo"]["name"], "shelem-scorekeeping")
        self.assertEqual(init["serverInfo"]["version"], __version__)
        self.assertIn("tools", init["capabilities"])

        self.assertEqual([t["name"] for t in responses["list"]["result"]["tools"]], [TOOL])

        call = responses["call"]["result"]
        self.assertFalse(call.get("isError", False))
        check_regression(self, call["structuredContent"])

        error = responses["error"]["result"]
        self.assertTrue(error["isError"])
        self.assertIn("Abbreviated", error["content"][0]["text"])

        stderr = b"".join(stderr_chunks).decode("utf-8", "replace")
        self.assertIn("Starting shelem-scorekeeping", stderr)


class CommandLineTest(unittest.TestCase):
    def test_version_flag(self):
        completed = subprocess.run(
            [sys.executable, "-m", "shelem_mcp", "--version"],
            capture_output=True,
            cwd=ROOT,
            env=server_env(),
            timeout=60,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn(__version__, completed.stdout.decode("utf-8"))


class RegistryMetadataTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = json.loads(SERVER_JSON.read_text(encoding="utf-8"))

    def test_server_json_matches_the_official_schema(self):
        schema = json.loads(REGISTRY_SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(self.server["$schema"], schema["$id"])
        jsonschema.Draft7Validator.check_schema(schema)
        errors = sorted(
            jsonschema.Draft7Validator(schema).iter_errors(self.server),
            key=lambda e: list(e.path),
        )
        self.assertEqual([e.message for e in errors], [])

    def test_official_registry_requirements(self):
        self.assertLessEqual(len(self.server["description"]), 100)
        self.assertNotIn("remotes", self.server)
        self.assertTrue(self.server["name"].startswith("io.github.khaleghika/"))
        self.assertEqual(self.server["repository"]["source"], "github")
        self.assertEqual(self.server["version"], __version__)
        (package,) = self.server["packages"]
        self.assertEqual(package["registryType"], "pypi")
        self.assertEqual(package["registryBaseUrl"], "https://pypi.org")
        self.assertEqual(package["version"], __version__)
        self.assertEqual(package["transport"], {"type": "stdio"})
        self.assertEqual(package["runtimeHint"], "uvx")
        self.assertEqual(
            self.server["$schema"],
            "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        )

        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        name = re.search(r'^name = "([^"]+)"', pyproject, re.MULTILINE).group(1)
        self.assertEqual(package["identifier"], name)
        self.assertIn(f'{name} = "shelem_mcp.server:main"', pyproject)

    def test_readme_carries_the_pypi_ownership_marker(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"<!-- mcp-name: {self.server['name']} -->", readme)
        self.assertIn("/v0.1/servers?search=io.github.khaleghika/shelem-scorekeeping", readme)

    def test_publish_workflow_follows_the_current_registry_guide(self):
        workflow = (ROOT / ".github" / "workflows" / "publish-mcp.yml").read_text(encoding="utf-8")
        for phrase in (
            'tags: ["v*"]',
            "id-token: write",
            "MCP_PUBLISHER_VERSION: v1.8.6",
            "cosign verify-blob",
            "login github-oidc",
            "./mcp-publisher publish",
            "pypa/gh-action-pypi-publish@release/v1",
            "sigstore/cosign-installer@6f9f17788090df1f26f669e9d70d6ae9567deba6",
        ):
            self.assertIn(phrase, workflow)
        self.assertNotIn("releases/latest", workflow)


class ReadmeExampleTest(unittest.IsolatedAsyncioTestCase):
    async def test_readme_tool_example_is_the_real_output(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        blocks = [json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", readme, re.DOTALL)]
        request = next(b for b in blocks if "team1_score" in b)
        response = next(b for b in blocks if "updated_team1_score" in b)
        self.assertEqual(request, REGRESSION_ARGS)
        async with Client(build_server()) as client:
            result = await client.call_tool(TOOL, request)
        self.assertEqual(result.structured_content, response)


if __name__ == "__main__":
    unittest.main()
