# Straight Connect

![](banner.png)

MCP server for communication service connectors. Currently supports Telegram with multi-account configuration. Designed for extensibility — more services (Slack, Discord, email, etc.) can be added later.

## Architecture

```
mcp/
├── server.py          # FastMCP entry point + ASGI middleware
├── telegram.py        # Telegram config, API client, tool definitions
├── requirements.txt   # Server dependencies
└── Dockerfile

src/
├── config.py          # Generates mcp.json from .env
└── chat.py            # Gradio + LangChain ReAct chat app

docker-compose.yaml
pyproject.toml
.env                   # Your configuration (not committed)
.env.example           # Configuration template
```

## Setup

1. Copy the environment template and fill in your values:

```bash
cp .env.example .env
```

2. Get bot tokens from [@BotFather](https://t.me/BotFather) on Telegram and add them to `.env`.

3. Start the MCP server:

```bash
docker compose up --build -d
```

4. Verify it's running:

```bash
docker compose logs mcp
```

## Configuration

All configuration lives in `.env`. See `.env.example` for the full template.

### Telegram Accounts

```env
# Comma-separated account labels
TELEGRAM_ACCOUNTS=nietzsche,aurelia

# Per-account bot tokens (label uppercased)
TELEGRAM_NIETZSCHE_BOT_TOKEN=your-token-here
TELEGRAM_AURELIA_BOT_TOKEN=your-token-here
```

### Tool Levels

Control which Telegram tools are available per account. Set a global default and optionally override per account:

```env
# Global default
TELEGRAM_LEVEL=basic

# Per-account override
TELEGRAM_NIETZSCHE_LEVEL=standard
TELEGRAM_AURELIA_LEVEL=full
```

| Level | Tools (cumulative) |
|-------|-------------------|
| **basic** | `get_me`, `send_message`, `get_updates` |
| **standard** | + `forward_message`, `edit_message_text`, `delete_message`, `send_photo`, `send_document` |
| **advanced** | + `get_chat`, `send_location`, `send_poll`, `pin_chat_message`, `unpin_chat_message`, `get_chat_member_count`, `get_chat_member` |
| **full** | + `send_audio`, `send_video`, `send_voice`, `send_sticker`, `copy_message`, `set_message_reaction`, `leave_chat`, `send_contact`, `send_venue` |

### Allowed Chats

Optionally restrict which chats a bot account can interact with. If set, any tool call targeting a chat not in the list will be rejected. If not set, all chats are allowed.

```env
# Comma-separated chat IDs (user IDs, group IDs, @channel_usernames)
TELEGRAM_NIETZSCHE_ALLOWED_CHATS=123456789,-1001234567890
TELEGRAM_AURELIA_ALLOWED_CHATS=987654321,@mychannel
```

This applies to all tools that take a `chat_id` parameter. For `forward_message` and `copy_message`, both source and destination chats are checked.

### Allowed User IDs

Restrict which Telegram users a bot account will interact with. Incoming updates from non-listed users are silently filtered out by `get_updates`. If not set, all users are allowed and a warning is logged at startup.

```env
TELEGRAM_NIETZSCHE_ALLOWED_USER_IDS=123456789
TELEGRAM_AURELIA_ALLOWED_USER_IDS=5138099108,987654321
```

### MCP Port

```env
MCP_PORT=9831
```

### Chat Model

Used by `uv run chat` for the Gradio test interface:

```env
OPENAI_API_BASE=http://localhost:8000/v1
OPENAI_API_KEY=not-needed
CHAT_MODEL=openai:your-model-name
```

## MCP Endpoints

Each account gets its own endpoint scoped by service and account label:

```
http://localhost:9831/mcp/telegram/<account>
```

Examples:
- `http://localhost:9831/mcp/telegram/nietzsche`
- `http://localhost:9831/mcp/telegram/aurelia`

There is no shared `/mcp` endpoint — each URL is exclusive to one account. This enables MCP clients to connect per-account with distinct tool namespaces.

## Client Tools

### Generate mcp.json

Print the MCP client configuration derived from your `.env`:

```bash
uv run config
```

Output:

```json
{
  "mcpServers": {
    "nietzsche": {
      "url": "http://localhost:9831/mcp/telegram/nietzsche"
    },
    "aurelia": {
      "url": "http://localhost:9831/mcp/telegram/aurelia"
    }
  }
}
```

### Chat Interface

Launch a Gradio web UI that connects to all configured MCP servers with a LangChain ReAct agent:

```bash
uv run chat
```

On startup it will:
1. Connect to each configured MCP server
2. List all available tools per account
3. Test the configured chat model
4. Launch the Gradio interface

Tool names are prefixed with the account label for disambiguation (e.g., `nietzsche_telegram_send_message`, `aurelia_telegram_get_updates`).

## How It Works

- **URL routing**: ASGI middleware rewrites `/mcp/<service>/<account>` to the internal FastMCP endpoint and sets the account context via `contextvars`
- **Dynamic registration**: Only configured services register their tools. If `TELEGRAM_ACCOUNTS` is empty, no Telegram tools exist
- **Level gating**: Tools are registered based on the maximum level across all accounts. Per-account level checks happen at call time, returning an error if the account's level is insufficient
- **Chat whitelisting**: Optional per-account `ALLOWED_CHATS` restricts which chats the bot can interact with
- **User filtering**: Optional per-account `ALLOWED_USER_IDS` filters incoming updates to only include messages from specified users
- **Extensibility**: New services follow the same pattern — add a config class, register tools conditionally, and the middleware routes automatically via `/mcp/<service>/<account>`
