# modules/main.py

import asyncio
import json
import os

import discord
from discord import app_commands
from discord.ext import commands

# Local modules
from modules import poll, tournament
from modules.config import CONFIG
from modules.dataStorage import (
    DEBUG_MODE,
    TOKEN,
    load_global_data,
    load_tournament_data,
    validate_channels,
    validate_permissions,
    load_env
)
from modules.logger import logger
from modules.reminder import match_reminder_loop
from modules.task_manager import add_task, cancel_all_tasks

# Important
load_env()





intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

EXTENSIONS = [
    "modules.setup",
    "modules.players",
    "modules.tournament",
    "modules.info",
    "modules.admin_tools",
    "modules.dev_tools",
]


# ========== EVENTS ==========
@bot.event
async def on_ready():
    language = CONFIG.bot.language.lower()

    logger.info(f"[STARTUP] Bot is online as {bot.user.name} (ID: {bot.user.id})")
    logger.info(f"[STARTUP] Language from config: {language}")
    logger.info(f"[STARTUP] DEBUG mode: {'active' if DEBUG_MODE else 'inactive'}")

    # Check important folders
    startup_folders = [
        "logs", "backups", "archive", "data", "locale", "configs",
        os.path.join("locale", language, "embeds")
    ]

    for folder in startup_folders:
        if not os.path.exists(folder):
            try:
                os.makedirs(folder)
                logger.info(f"[STARTUP] Folder created: {folder}")
            except (OSError, PermissionError) as e:
                logger.error(f"[STARTUP] Error creating {folder}: {e}")
        else:
            logger.info(f"[STARTUP] Folder exists: {folder}")

    # Check essential files
    required_files = [
        "configs/bot.json",
        "configs/tournament.json",
        "configs/features.json",
        "data/data.json",
        "data/tournament.json",
        "data/games.json",
        f"locale/{language}/names_{language}.json",
    ]

    logger.info("[STARTUP] File validation starting...")
    for path in required_files:
        if not os.path.exists(path):
            logger.error(f"[STARTUP] ❌ File missing: {path}")
        else:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    json.load(f)
                logger.info(f"[STARTUP] ✅ File OK: {path}")
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"[STARTUP] ❌ Error parsing {path}: {e}")
    logger.info("[STARTUP] File validation completed.")

    # Validate channels and permissions
    logger.info("[STARTUP] Validating channels and permissions...")
    try:
        await validate_channels(bot)
        logger.info("[STARTUP] ✅ Channel validation passed")
    except Exception as e:
        logger.error(f"[STARTUP] ❌ Channel validation failed: {e}")

    # Validate permissions for all guilds the bot is in
    try:
        for guild in bot.guilds:
            await validate_permissions(guild)
        logger.info("[STARTUP] ✅ Permission validation passed")
    except Exception as e:
        logger.error(f"[STARTUP] ❌ Permission validation failed: {e}")


     # Stop old tasks
    try:
        cancel_all_tasks()
        logger.info("[STARTUP] ✅ Old background tasks terminated")
    except Exception as e:
        logger.error(f"[STARTUP] ⚠️ Error terminating old tasks: {e}")

    # Start reminder system
    try:
        reminder_channel_id = CONFIG.get_channel_id("reminder")
        channel = bot.get_channel(reminder_channel_id)

        if channel:
            add_task("reminder_loop", bot.loop.create_task(match_reminder_loop(channel)))
            logger.info("[STARTUP] ✅ Reminder subsystem started")
        else:
            logger.error(f"[STARTUP] ❌ Reminder channel with ID {reminder_channel_id} not found!")
    except Exception as e:
        logger.error(f"[STARTUP] ❌ Failed to start reminder system: {e}")

    # Resync slash commands
    try:
        synced = await bot.tree.sync()
        if len(synced) == 0:
            logger.warning("[STARTUP] ⚠️ No slash commands synchronized.")
        else:
            logger.info(f"[STARTUP] ✅ Slash commands synchronized ({len(synced)} commands).")
    except Exception as e:
        logger.error(f"[STARTUP] ❌ Slash command sync failed: {e}")

    logger.info("[STARTUP] ✅ Initialization completed.\n")


@bot.event
async def on_error(event, *args, **kwargs):
    """Global error handler for events."""
    logger.error(f"[ERROR] Error in event '{event}': {args}, {kwargs}", exc_info=True)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Global error handler for slash commands."""
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"⏳ Command is on cooldown. Try again in {error.retry_after:.1f} seconds.",
            ephemeral=True
        )
    elif isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.",
            ephemeral=True
        )
    elif isinstance(error, app_commands.CommandNotFound):
        logger.warning(f"[COMMAND] Command not found: {interaction.command.name if interaction.command else 'unknown'}")
    else:
        logger.error(f"[COMMAND ERROR] Error in command '{interaction.command.name if interaction.command else 'unknown'}': {error}", exc_info=error)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ An error occurred while executing this command. Please try again or contact an admin.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "❌ An error occurred while executing this command.",
                    ephemeral=True
                )
        except Exception:
            pass  # Fail silently if we can't send error message


# ========== LOAD EXTENSIONS & START BOT ==========
async def main():
    """Main entry point for the bot. Loads extensions and starts the bot."""
    logger.info("[SYSTEM] Starting bot initialization...")

    # Track extension loading
    loaded_extensions = []
    failed_extensions = []

    # Load extensions/cogs
    for ext in EXTENSIONS:
        try:
            await bot.load_extension(ext)
            loaded_extensions.append(ext)
            logger.info(f"[SYSTEM] ✅ Extension loaded: {ext}")
        except Exception as e:
            failed_extensions.append(ext)
            logger.error(f"[SYSTEM] ❌ Error loading extension {ext}: {e}")

    # Summary of extension loading
    logger.info(f"[SYSTEM] Extension loading summary: {len(loaded_extensions)}/{len(EXTENSIONS)} loaded successfully")
    if failed_extensions:
        logger.warning(f"[SYSTEM] Failed extensions: {', '.join(failed_extensions)}")

    # Validate TOKEN before starting
    if not TOKEN:
        logger.critical("[SYSTEM] ❌ CRITICAL: Discord bot token not found! Check your .env file.")
        return

    # Start bot (blocks until the end)
    try:
        logger.info("[SYSTEM] Starting Discord bot connection...")
        await bot.start(TOKEN)
    except discord.LoginFailure:
        logger.critical("[SYSTEM] ❌ CRITICAL: Login failed - invalid bot token!")
    except discord.PrivilegedIntentsRequired:
        logger.critical("[SYSTEM] ❌ CRITICAL: Privileged intents required - enable them in Discord Developer Portal!")
    except Exception as e:
        logger.critical(f"[SYSTEM] ❌ CRITICAL: Bot crashed during startup: {e}")


if __name__ == "__main__":
    import sys
    from pathlib import Path

    # Add project root to Python path if running directly
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("[SYSTEM] Bot shutdown requested by user (Ctrl+C)")
    except Exception as e:
        logger.critical(f"[SYSTEM] ❌ CRITICAL: Unexpected error in main loop: {e}")
