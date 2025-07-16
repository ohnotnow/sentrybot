import discord
from discord.ext import commands
import asyncio
import os
from contextlib import AsyncExitStack
import logging

# MCP imports
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Claude API imports
from anthropic import AsyncAnthropic

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SentryBot(commands.Bot):
    def __init__(self):
        # Discord bot setup
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)

        # Initialize API clients
        self.claude_client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        # MCP session for Sentry
        self.sentry_session = None
        self.sentry_tools = []
        self.exit_stack = AsyncExitStack()

    async def setup_hook(self):
        """Called when the bot is starting up"""
        logger.info("Connecting to Sentry MCP server...")
        await self.connect_to_sentry()

    async def connect_to_sentry(self):
        """Connect to Sentry MCP server"""
        try:
            # Sentry MCP server parameters
            server_params = StdioServerParameters(
                command="npx",
                args=[
                    "@sentry/mcp-server@latest",
                    f"--access-token={os.getenv('SENTRY_AUTH_TOKEN')}",
                    f"--host={os.getenv('SENTRY_HOST', 'sentry.io')}"
                ],
                env=None
            )

            # Start the Sentry MCP server
            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            )

            read_stream, write_stream = stdio_transport

            self.sentry_session = await self.exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )

            # Initialize the session
            await self.sentry_session.initialize()

            # Get available Sentry tools
            tools_response = await self.sentry_session.list_tools()
            self.sentry_tools = tools_response.tools

            logger.info(f"Connected to Sentry with tools: {[tool.name for tool in self.sentry_tools]}")

        except Exception as e:
            logger.error(f"Failed to connect to Sentry: {e}")
            self.sentry_session = None

    async def ask_claude(self, user_message: str):
        """Ask Claude with access to Sentry tools"""
        try:
            # Start conversation
            messages = [{"role": "user", "content": user_message}]

            # Prepare Sentry tools for Claude
            tools = []
            if self.sentry_session and self.sentry_tools:
                tools = [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": tool.inputSchema
                    }
                    for tool in self.sentry_tools
                ]

            # Keep looping until Claude gives a final answer
            max_iterations = 10  # Prevent infinite loops
            iteration = 0

            while iteration < max_iterations:
                iteration += 1

                # Query Claude
                claude_params = {
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 1000,
                    "messages": messages
                }

                if tools:
                    claude_params["tools"] = tools

                response = await self.claude_client.messages.create(**claude_params)

                # Add Claude's response to the conversation
                messages.append({"role": "assistant", "content": response.content})

                # Check if Claude made tool calls
                tool_calls_made = False
                tool_results = []

                for content in response.content:
                    if content.type == "tool_use" and self.sentry_session:
                        tool_calls_made = True

                        try:
                            # Execute the tool
                            tool_result = await self.sentry_session.call_tool(
                                content.name,
                                content.input
                            )

                            # Prepare the result for Claude
                            result_content = str(tool_result.content[0].text) if tool_result.content else "No result"

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": content.id,
                                "content": result_content
                            })

                        except Exception as e:
                            logger.error(f"Tool execution error: {e}")
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": content.id,
                                "content": f"Error: {str(e)}"
                            })

                # If Claude made tool calls, send the results back
                if tool_calls_made:
                    messages.append({"role": "user", "content": tool_results})
                else:
                    # Claude didn't make tool calls, so we have the final answer
                    final_text = ""
                    for content in response.content:
                        if content.type == "text":
                            final_text += content.text

                    return final_text if final_text else "I couldn't process that request."

            return "Sorry, the request took too many steps to complete."

        except Exception as e:
            logger.error(f"Error asking Claude: {e}")
            return f"Sorry, I encountered an error: {str(e)}"

    async def on_ready(self):
        """Called when the bot is ready"""
        logger.info(f'{self.user} has connected to Discord!')
        sentry_status = "Connected" if self.sentry_session else "Not Connected"
        logger.info(f'Sentry Status: {sentry_status}')

    async def on_message(self, message):
        """Handle incoming messages"""
        if message.author == self.user:
            return
        await self.process_commands(message)

    async def close(self):
        """Clean up when shutting down"""
        logger.info("Shutting down bot...")
        if self.exit_stack:
            await self.exit_stack.aclose()
        await super().close()

# Simple commands
@commands.command(name='ask')
async def ask(ctx, *, question: str):
    """Ask about Sentry data"""
    async with ctx.typing():
        response = await ctx.bot.ask_claude(question)

        # Split long responses for Discord
        if len(response) > 2000:
            for i in range(0, len(response), 2000):
                await ctx.send(response[i:i+2000])
        else:
            await ctx.send(response)

@commands.command(name='status')
async def status(ctx):
    """Check Sentry connection status"""
    if ctx.bot.sentry_session:
        tool_count = len(ctx.bot.sentry_tools)
        await ctx.send(f"✅ Connected to Sentry with {tool_count} tools available")
    else:
        await ctx.send("❌ Not connected to Sentry")

# Main execution
async def main():
    bot = SentryBot()
    bot.add_command(ask)
    bot.add_command(status)

    try:
        await bot.start(os.getenv("DISCORD_BOT_TOKEN"))
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())
