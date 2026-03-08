import json
import os

from dotenv import load_dotenv


def build_mcp_json() -> dict:
    """Build mcp.json from .env configuration."""
    load_dotenv()

    servers = {}
    port = os.environ.get("MCP_PORT", "9831")
    base = f"http://localhost:{port}/mcp"

    # Telegram
    accounts_raw = os.environ.get("TELEGRAM_ACCOUNTS", "")
    if accounts_raw.strip():
        for label in accounts_raw.split(","):
            label = label.strip()
            if not label:
                continue
            token_key = f"TELEGRAM_{label.upper()}_BOT_TOKEN"
            if os.environ.get(token_key):
                servers[label.lower()] = {
                    "url": f"{base}/telegram/{label.lower()}"
                }

    return {"mcpServers": servers}


def main():
    print(json.dumps(build_mcp_json(), indent=2))


if __name__ == "__main__":
    main()
