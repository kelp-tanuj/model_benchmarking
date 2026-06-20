"""Spike 0 — trivial stdio MCP server.

Purpose: validate that `claude -p` can connect to a stdio MCP server headless, call a
typed tool, and read back its structured result. The `measured_candidate_call_stub` tool
stands in for the real measured call (no provider key / no network needed for the spike) —
it returns canned timing/usage so we can confirm the agent reads numbers off the tool rather
than inventing them.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("spike")


@mcp.tool()
def measured_candidate_call_stub(prompt: str) -> dict:
    """Stand-in for the real measured candidate call. Returns canned output + metrics.

    In the real system this performs a timed HTTP round-trip and returns measured numbers;
    here it returns fixed values so the spike can confirm MCP wiring end to end.
    """
    return {
        "output": f"[stub answer to: {prompt}]",
        "latency_ms": 123,
        "tokens_in": 42,
        "tokens_out": 7,
        "cost": 0.000123,
    }


if __name__ == "__main__":
    mcp.run()  # stdio transport by default
