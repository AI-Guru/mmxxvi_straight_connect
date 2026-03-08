import re

import uvicorn
from fastmcp import FastMCP

from telegram import TelegramConfig, account_override, register_telegram_tools

mcp = FastMCP(
    "Straight Connect MCP Server",
    instructions="""This server provides tools for communicating via messaging services.

Currently supported services:
- Telegram: Send and receive messages through configured Telegram bot accounts.

Use telegram_list_accounts to discover which bot accounts are configured,
then use the account label with other telegram_* tools.""",
)

# --- Dynamic service registration ---

telegram_config = TelegramConfig()
if telegram_config.is_configured:
    register_telegram_tools(mcp, telegram_config)

# --- Account-from-path middleware ---

# Matches /mcp/<service>/<account> and captures (service, account)
_ACCOUNT_PATH_RE = re.compile(r"^/mcp/(\w+)/(\w+)$")


class AccountPathMiddleware:
    """Rewrites /mcp/<service>/<account> to /_mcp and sets account_override."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope["path"]
            match = _ACCOUNT_PATH_RE.match(path)
            if match:
                service, account = match.group(1), match.group(2)
                scope = dict(scope, path="/_mcp")
                account_override.set(account)
        await self.app(scope, receive, send)


# --- Start server ---

if __name__ == "__main__":
    app = mcp.http_app(path="/_mcp", transport="streamable-http")
    app = AccountPathMiddleware(app)
    uvicorn.run(app, host="0.0.0.0", port=8000)
