# SentryBot

A Discord bot that integrates with Sentry via the Sentry MCP protocol and uses Anthropic’s Claude AI to answer user questions about Sentry data.

---

## Features

- Connects to a Sentry MCP server to list and call tools.
- Interacts with Anthropic Claude (via `AsyncAnthropic`) to generate responses.
- Provides two slash-style commands:
  - **!ask**: Ask Claude a question about Sentry events/data.
  - **!status**: Check Sentry connection status and tool availability.
- Graceful startup and shutdown with proper logging.

---

## Repository

```bash
git clone https://github.com/ohnotnow/sentrybot.git
cd sentrybot
```

---

## Prerequisites

- **git** (already installed)
- **Python** 3.8 or higher
- **Discord Bot Token** (create at https://discord.com/developers/applications)
- **Anthropic API Key** (`ANTHROPIC_API_KEY`)
- **Sentry Auth Token** (`SENTRY_AUTH_TOKEN`)
- _(Optional)_ **Sentry Host** (`SENTRY_HOST`, defaults to `sentry.io`)
- **uv** CLI tool for Python
  - Documentation: https://docs.astral.sh/uv/

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/ohnotnow/sentrybot.git
cd sentrybot
```

### 2. Prepare environment variables

Create a file named `.env` in the project root:

```
DISCORD_BOT_TOKEN=<your_discord_bot_token>
ANTHROPIC_API_KEY=<your_anthropic_api_key>
SENTRY_AUTH_TOKEN=<your_sentry_auth_token>
# Optional:
SENTRY_HOST=<your_sentry_host>  # defaults to sentry.io
```

### 3. Install dependencies

Use `uv` to synchronize dependencies:

```bash
uv sync
```

> Note: If you do not have `uv` installed, follow the installation instructions at https://docs.astral.sh/uv/.

---

## Running the Bot

Once dependencies are installed and `.env` is configured, start the bot with:

```bash
uv run main.py
```

The bot will:

1. Load environment variables via `python-dotenv`.
2. Connect to the Sentry MCP server (using `npx @sentry/mcp-server@latest`).
3. Initialize the Anthropic Claude client.
4. Register the `!ask` and `!status` commands.
5. Begin listening for messages in Discord.

---

## Usage

In any channel where the bot is invited:

- **!ask** _<question>_  
  Ask Claude about Sentry data.  
  Example:  
  ```
  !ask How many errors occurred in the last 24 hours?
  ```

- **!status**  
  Check if the bot is connected to Sentry and how many tools are available.  
  Example:
  ```
  !status
  ```

---

## Platform Notes

Installation and usage commands are identical on macOS, Ubuntu, and Windows when using a POSIX-like shell. If you use PowerShell on Windows, environment variables can be set per session:

```powershell
$Env:DISCORD_BOT_TOKEN="..."
$Env:ANTHROPIC_API_KEY="..."
$Env:SENTRY_AUTH_TOKEN="..."
uv sync
uv run main.py
```

---

## Logging

The bot uses Python’s built-in `logging` module at `INFO` level. Logs include:

- Connection status to Discord and Sentry.
- Errors during setup, tool calls, or Claude queries.
- Shutdown notifications.

---

## License

This project is licensed under the MIT License.  
See the [LICENSE](LICENSE) file for details.
