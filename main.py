import discord
from discord.ext import commands
import asyncio
import os
from contextlib import AsyncExitStack
import logging
from collections import defaultdict, deque
import json
from datetime import datetime, timedelta

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

        # Memory storage - keep last 10 messages per user/channel
        self.conversation_memory = defaultdict(lambda: deque(maxlen=10))
        self.memory_timeout = timedelta(hours=2)  # Clear old conversations

    def get_memory_key(self, ctx):
        """Generate a unique key for this conversation context"""
        # Option 1: Per user (remembers across all channels)
        # return f"user_{ctx.author.id}"

        # Option 2: Per channel (all users in channel share memory)
        # return f"channel_{ctx.channel.id}"

        # Option 3: Per user per channel (separate memory per user per channel)
        return f"user_{ctx.author.id}_channel_{ctx.channel.id}"

    def add_to_memory(self, ctx, role: str, content: str):
        """Add a message to conversation memory"""
        memory_key = self.get_memory_key(ctx)

        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now()
        }

        self.conversation_memory[memory_key].append(message)

    def get_conversation_history(self, ctx):
        """Get recent conversation history for Claude"""
        memory_key = self.get_memory_key(ctx)
        messages = []

        # Clean up old messages
        now = datetime.now()
        memory = self.conversation_memory[memory_key]

        # Remove messages older than timeout
        while memory and now - memory[0]["timestamp"] > self.memory_timeout:
            memory.popleft()

        # Convert to Claude format
        for msg in memory:
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

        return messages

    async def setup_hook(self):
        """Called when the bot is starting up"""
        logger.info("Connecting to Sentry MCP server...")
        await self.connect_to_sentry()

    async def connect_to_sentry(self):
        """Connect to Sentry MCP server"""
        try:
            server_params = StdioServerParameters(
                command="npx",
                args=[
                    "@sentry/mcp-server@latest",
                    f"--access-token={os.getenv('SENTRY_AUTH_TOKEN')}",
                    f"--host={os.getenv('SENTRY_HOST', 'sentry.io')}"
                ],
                env=None
            )

            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            )

            read_stream, write_stream = stdio_transport

            self.sentry_session = await self.exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )

            await self.sentry_session.initialize()

            tools_response = await self.sentry_session.list_tools()
            self.sentry_tools = tools_response.tools

            logger.info(f"Connected to Sentry with tools: {[tool.name for tool in self.sentry_tools]}")

        except Exception as e:
            logger.error(f"Failed to connect to Sentry: {e}")
            self.sentry_session = None

    async def ask_claude_with_memory(self, ctx, user_message: str):
        """Ask Claude with conversation history"""
        system_prompt = """
        You are a helpful assistant that can answer questions about Sentry data. You are also able to use the tools
        provided to you to answer questions.

        For your final response - please assume the user is a technically minded, experienced software engineer.  Remember
        to be friendly and supportive - they might be stressed or frustrated as they are dealing with a bug or issue.

        If the user gives you an sentry issue id, you can use that to help you understand which Sentry project the issue
        is about - the format of a sentry issue id is "PROJECT_NAME-ISSUE" so from that you can determine the project
        name when you are using the tools to look up information.
        """

        try:
            # Get conversation history
            messages = self.get_conversation_history(ctx)

            # Add the new user message
            messages.append({"role": "user", "content": user_message})

            # Store user message in memory
            self.add_to_memory(ctx, "user", user_message)

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
            max_iterations = 10
            iteration = 0

            while iteration < max_iterations:
                iteration += 1

                claude_params = {
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 1000,
                    "messages": messages,
                    "system": system_prompt
                }

                if tools:
                    claude_params["tools"] = tools

                response = await self.claude_client.messages.create(**claude_params)

                messages.append({"role": "assistant", "content": response.content})

                tool_calls_made = False
                tool_results = []

                for content in response.content:
                    if content.type == "tool_use" and self.sentry_session:
                        tool_calls_made = True
                        logger.info(f"Tool call made: {content.name}")
                        logger.info(f"Tool call input: {content.input}")

                        try:
                            tool_result = await self.sentry_session.call_tool(
                                content.name,
                                content.input
                            )

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

                if tool_calls_made:
                    messages.append({"role": "user", "content": tool_results})
                else:
                    # Final answer - extract text and store in memory
                    final_text = ""
                    for content in response.content:
                        if content.type == "text":
                            final_text += content.text

                    # Store Claude's response in memory
                    if final_text:
                        self.add_to_memory(ctx, "assistant", final_text)

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

        # if we only want to response to messages from a specific server, we can add a check here
        if int(message.guild.id) != int(os.getenv("DISCORD_SERVER_ID")):
            logger.info(f"Message from {message.author} in {message.guild.name} ignored")
            logger.info(f"Guild ID: {message.guild.id}")
            logger.info(f"Server ID: {os.getenv('DISCORD_SERVER_ID')}")
            return

        # Process commands first
        await self.process_commands(message)

        # If it wasn't a command and the bot was mentioned or it's a DM, respond
        if not message.content.startswith(self.command_prefix):
            # Check if bot was mentioned or it's a DM
            if self.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
                async with message.channel.typing():
                    # Remove the mention from the message content
                    content = message.content.replace(f'<@{self.user.id}>', '').strip()
                    if not content:
                        content = "Hello!"

                    response = await self.ask_claude_with_memory(message, content)

                    if len(response) > 2000:
                        for i in range(0, len(response), 2000):
                            await message.reply(response[i:i+2000])
                    else:
                        await message.reply(response)

    async def close(self):
        """Clean up when shutting down"""
        logger.info("Shutting down bot...")
        if self.exit_stack:
            await self.exit_stack.aclose()
        await super().close()

# Commands
@commands.command(name='ask')
async def ask(ctx, *, question: str):
    """Ask about Sentry data with memory"""
    async with ctx.typing():
        response = await ctx.bot.ask_claude_with_memory(ctx, question)

        if len(response) > 2000:
            for i in range(0, len(response), 2000):
                await ctx.send(response[i:i+2000])
        else:
            await ctx.send(response)

@commands.command(name='forget')
async def forget(ctx):
    """Clear conversation memory"""
    memory_key = ctx.bot.get_memory_key(ctx)
    ctx.bot.conversation_memory[memory_key].clear()
    await ctx.send("🧠 Conversation memory cleared!")

@commands.command(name='memory')
async def memory_status(ctx):
    """Check memory status"""
    memory_key = ctx.bot.get_memory_key(ctx)
    message_count = len(ctx.bot.conversation_memory[memory_key])
    await ctx.send(f"💭 I remember {message_count} messages from our conversation")

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
    bot.add_command(forget)
    bot.add_command(memory_status)
    bot.add_command(status)

    try:
        await bot.start(os.getenv("DISCORD_BOT_TOKEN"))
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())
