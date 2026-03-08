import contextvars
import os
from typing import Optional

import httpx

TELEGRAM_API_BASE = "https://api.telegram.org"

# Set by middleware when account is determined from URL path
account_override: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "account_override", default=None
)


class TelegramConfig:
    """Parse TELEGRAM_ACCOUNTS and corresponding bot tokens from environment."""

    def __init__(self):
        self.accounts: dict[str, str] = {}
        accounts_raw = os.environ.get("TELEGRAM_ACCOUNTS", "")
        if not accounts_raw.strip():
            return
        for label in accounts_raw.split(","):
            label = label.strip()
            if not label:
                continue
            env_key = f"TELEGRAM_{label.upper()}_BOT_TOKEN"
            token = os.environ.get(env_key, "")
            if token:
                self.accounts[label.lower()] = token

    @property
    def is_configured(self) -> bool:
        return len(self.accounts) > 0

    def get_token(self, account: str) -> str | None:
        return self.accounts.get(account.lower())

    def list_accounts(self) -> list[str]:
        return list(self.accounts.keys())


async def telegram_api_call(
    token: str, method: str, params: dict | None = None
) -> dict:
    """Make a call to the Telegram Bot API."""
    url = f"{TELEGRAM_API_BASE}/bot{token}/{method}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        if params:
            response = await client.post(url, json=params)
        else:
            response = await client.get(url)
        response.raise_for_status()
        return response.json()


def _resolve_account(config: TelegramConfig, account: Optional[str]) -> tuple[str | None, dict | None]:
    """Resolve account label to token. Returns (token, error_dict)."""
    # URL path override takes priority
    override = account_override.get()
    if override is not None:
        account = override
    if account is None:
        # Single-account mode: auto-select the only account
        accounts = config.list_accounts()
        if len(accounts) == 1:
            account = accounts[0]
        else:
            return None, {"error": "Multiple accounts configured. Specify the account parameter."}
    token = config.get_token(account)
    if not token:
        return None, {"error": f"Unknown account: {account}. Use telegram_list_accounts to see available accounts."}
    return token, None


def register_telegram_tools(mcp, config: TelegramConfig):
    """Register all Telegram MCP tools."""

    single_account = len(config.accounts) == 1

    @mcp.tool()
    async def telegram_list_accounts() -> dict:
        """List all configured Telegram bot accounts.

        Returns the account labels that can be used with other telegram_* tools.
        """
        accounts = config.list_accounts()
        return {"accounts": accounts, "count": len(accounts)}

    @mcp.tool()
    async def telegram_get_me(account: Optional[str] = None) -> dict:
        """Get information about a Telegram bot account.

        Use this to verify that an account is correctly configured.

        Args:
            account: Account label (e.g. "nietzsche"). Optional when only one account is configured.
        """
        token, err = _resolve_account(config, account)
        if err:
            return err
        try:
            return await telegram_api_call(token, "getMe")
        except httpx.HTTPStatusError as e:
            return {"error": f"Telegram API error: {e.response.status_code}"}
        except httpx.RequestError as e:
            return {"error": f"Request failed: {str(e)}"}

    @mcp.tool()
    async def telegram_send_message(
        chat_id: str,
        text: str,
        account: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> dict:
        """Send a text message via a Telegram bot.

        Args:
            chat_id: Target chat ID (user ID, group ID, or @channel_username).
            text: Message text to send (max 4096 characters).
            account: Account label (e.g. "nietzsche"). Optional when only one account is configured.
            parse_mode: Optional formatting: "HTML", "Markdown", or "MarkdownV2".
        """
        token, err = _resolve_account(config, account)
        if err:
            return err
        params = {"chat_id": chat_id, "text": text}
        if parse_mode:
            params["parse_mode"] = parse_mode
        try:
            return await telegram_api_call(token, "sendMessage", params)
        except httpx.HTTPStatusError as e:
            return {"error": f"Telegram API error: {e.response.status_code}"}
        except httpx.RequestError as e:
            return {"error": f"Request failed: {str(e)}"}

    @mcp.tool()
    async def telegram_get_updates(
        account: Optional[str] = None,
        limit: int = 10,
        offset: Optional[int] = None,
    ) -> dict:
        """Get recent incoming updates (messages, etc.) for a Telegram bot.

        Args:
            account: Account label (e.g. "nietzsche"). Optional when only one account is configured.
            limit: Maximum number of updates to retrieve (1-100, default 10).
            offset: Update ID offset. Pass the highest update_id + 1 from previous results to acknowledge older updates.
        """
        token, err = _resolve_account(config, account)
        if err:
            return err
        params: dict = {"limit": min(max(limit, 1), 100), "timeout": 0}
        if offset is not None:
            params["offset"] = offset
        try:
            return await telegram_api_call(token, "getUpdates", params)
        except httpx.HTTPStatusError as e:
            return {"error": f"Telegram API error: {e.response.status_code}"}
        except httpx.RequestError as e:
            return {"error": f"Request failed: {str(e)}"}
