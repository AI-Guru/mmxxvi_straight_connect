import logging
import re

import uvicorn
from fastapi import FastAPI
from fastmcp import FastMCP

from telegram import TelegramConfig, account_override, register_telegram_tools
from telegram_api import create_telegram_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("connect")

mcp = FastMCP(
    "Straight Connect MCP Server",
    instructions="""This server provides tools for communicating via messaging services.

Currently supported services:
- Telegram: Send and receive messages through configured Telegram bot accounts.

Each MCP endpoint is scoped to a single account via the URL path.
Available tools depend on the configured level (basic/standard/advanced/full).""",
)

# --- Dynamic service registration ---

telegram_config = TelegramConfig()
if telegram_config.is_configured:
    register_telegram_tools(mcp, telegram_config)
    for acct in telegram_config.list_accounts():
        level = telegram_config.get_level(acct)
        chats = telegram_config.get_allowed_chats(acct)
        uids = telegram_config.get_allowed_user_ids(acct)
        parts = [f"level={level}"]
        if chats is not None:
            parts.append(f"allowed_chats={chats}")
        if uids is not None:
            parts.append(f"allowed_user_ids={uids}")
        else:
            logger.warning("Account '%s': no ALLOWED_USER_IDS set — all users allowed", acct)
        logger.info("Telegram account '%s': %s", acct, ", ".join(parts))
else:
    logger.info("No Telegram accounts configured")

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


# --- Build combined app ---

def create_app() -> FastAPI:
    """Create the combined FastAPI app with MCP and REST API."""
    # Create main FastAPI app
    app = FastAPI(
        title="Straight Connect",
        description="MCP Server and REST API for messaging services",
        version="1.0.0",
    )

    # Mount REST API routes
    if telegram_config.is_configured:
        telegram_router = create_telegram_router(telegram_config)
        app.include_router(telegram_router)
        logger.info("REST API mounted at /api/telegram")

    # Mount MCP app
    mcp_app = mcp.http_app(path="/_mcp", transport="streamable-http")
    app.mount("/_mcp", mcp_app)
    logger.info("MCP server mounted at /_mcp")

    return app


# --- Start server ---

if __name__ == "__main__":
    app = create_app()
    app = AccountPathMiddleware(app)
    uvicorn.run(app, host="0.0.0.0", port=8000)
