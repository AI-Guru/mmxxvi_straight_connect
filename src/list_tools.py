import asyncio
import json

import httpx
from dotenv import load_dotenv

from src.config import build_mcp_json


async def _list_tools():
    load_dotenv()
    mcp_config = build_mcp_json()
    servers = mcp_config["mcpServers"]

    if not servers:
        print("No MCP servers configured.")
        return

    for name, cfg in servers.items():
        url = cfg["url"]
        print(f"\n{name} ({url})")

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Initialize session
            init_resp = await client.post(
                url,
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 0,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "list_tools", "version": "1.0"},
                    },
                },
            )

            session_id = init_resp.headers.get("mcp-session-id")
            if not session_id:
                print("  ERROR: No session ID returned")
                continue

            # List tools
            tools_resp = await client.post(
                url,
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                    "Mcp-Session-Id": session_id,
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                },
            )

            # Parse SSE response
            for line in tools_resp.text.splitlines():
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    tools = data.get("result", {}).get("tools", [])
                    for tool in tools:
                        desc = tool.get("description", "").splitlines()[0]
                        print(f"  - {tool['name']}: {desc}")
                    if not tools:
                        print("  (no tools)")
                    break


def main():
    asyncio.run(_list_tools())


if __name__ == "__main__":
    main()
