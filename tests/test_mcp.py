"""Real official-SDK initialization and subprocess stdio, without model calls."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hydra_sdlc.mcp import create_server


class ControllerFixture:
    def status(self):
        return [{"repository": "example/product", "wait_reason": "human_decision"}]

    async def begin(self, url):
        if url != "https://github.com/example/product/issues/4":
            raise ValueError("Issue outside installed allowlist")
        return {"action": "waiting", "reason": "human_decision"}

    async def checkpoint(self, *args):
        return {"action": "waiting", "reason": "stop_requested"}

    async def advance(self, *args):
        return {"action": "waiting", "reason": "ci_pending"}


@unittest.skipUnless(importlib.util.find_spec("mcp"), "optional pinned MCP SDK not installed")
class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_inprocess_schema_and_refusal(self):
        from mcp import Client
        async with Client(create_server(ControllerFixture())) as client:
            listed = await client.list_tools()
            self.assertEqual({tool.name for tool in listed.tools},
                {"hydra_status", "hydra_begin", "hydra_checkpoint", "hydra_verify", "hydra_deliver"})
            checkpoint = next(tool for tool in listed.tools if tool.name == "hydra_checkpoint")
            self.assertIn("step_id", checkpoint.input_schema["required"])
            with self.assertLogs(level="ERROR"):
                result = await client.call_tool("hydra_begin", {"issue_url": "https://github.com/foreign/product/issues/4"})
            self.assertTrue(result.is_error)

    async def test_real_stdio_initialize_list_and_read(self):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters
        params = StdioServerParameters(command=sys.executable,
            args=[str(Path(__file__).resolve()), "--fixture"],
            cwd=str(Path(__file__).resolve().parents[1]))
        async with Client(params) as client:
            self.assertEqual(len((await client.list_tools()).tools), 5)
            result = await client.call_tool("hydra_status", {})
            self.assertFalse(result.is_error)
            data = result.structured_content or json.loads(result.content[0].text)
            self.assertEqual(data["projects"][0]["wait_reason"], "human_decision")


if __name__ == "__main__":
    if sys.argv[1:] == ["--fixture"]:
        create_server(ControllerFixture()).run(transport="stdio")
    else:
        unittest.main()
