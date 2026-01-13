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

    logger.info("═" * 70)
    logger.info(f"[STARTUP] 🤖 Bot: {bot.user.name} (ID: {bot.user.id})")
    logger.info(f"[STARTUP] 🌍 Language: {language} | DEBUG: {'ON' if DEBUG_MODE else 'OFF'}")

    # Show connected servers
    if len(bot.guilds) == 0:
        logger.warning("[STARTUP] ⚠️  Servers: Not connected to any server!")
    elif len(bot.guilds) == 1:
        guild = bot.guilds[0]
        logger.info(f"[STARTUP] 🏠 Server: {guild.name} ({len(guild.members)} members)")
    else:
        guild_names = ", ".join([f"{g.name}" for g in bot.guilds])
        logger.info(f"[STARTUP] 🏠 Servers: {len(bot.guilds)} ({guild_names})")

    logger.info("═" * 70)

    # Check important folders (only log errors or creation)
    startup_folders = [
        "logs", "backups", "archive", "data", "locale", "configs",
        os.path.join("locale", language, "embeds")
    ]

    folders_created = []
    for folder in startup_folders:
        if not os.path.exists(folder):
            try:
                os.makedirs(folder)
                folders_created.append(folder)
            except (OSError, PermissionError) as e:
                logger.error(f"[STARTUP] ❌ Error creating {folder}: {e}")
        elif DEBUG_MODE:
            logger.debug(f"[STARTUP] Folder exists: {folder}")

    if folders_created:
        logger.info(f"[STARTUP] 📁 Created folders: {', '.join(folders_created)}")
    elif DEBUG_MODE:
        logger.debug(f"[STARTUP] ✅ All {len(startup_folders)} folders exist")

    # Check essential files (only log errors)
    required_files = [
        "configs/bot.json",
        "configs/tournament.json",
        "configs/features.json",
        "data/data.json",
        "data/tournament.json",
        "data/games.json",
        f"locale/{language}/names_{language}.json",
    ]

    file_errors = []
    for path in required_files:
        if not os.path.exists(path):
            logger.error(f"[STARTUP] ❌ File missing: {path}")
            file_errors.append(path)
        else:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    json.load(f)
                if DEBUG_MODE:
                    logger.debug(f"[STARTUP] ✅ File OK: {path}")
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"[STARTUP] ❌ Error parsing {path}: {e}")
                file_errors.append(path)

    if not file_errors:
        logger.info(f"[STARTUP] ✅ All {len(required_files)} files validated")
    else:
        logger.error(f"[STARTUP] ❌ {len(file_errors)} file(s) failed validation")

    # Validate channels and permissions (compact logging)
    try:
        await validate_channels(bot)
        logger.info("[STARTUP] ✅ Channels validated")
    except Exception as e:
        logger.error(f"[STARTUP] ❌ Channel validation failed: {e}")

    # Validate permissions for all guilds the bot is in
    try:
        for guild in bot.guilds:
            await validate_permissions(guild)
        logger.info("[STARTUP] ✅ Permissions validated")
    except Exception as e:
        logger.error(f"[STARTUP] ❌ Permission validation failed: {e}")


    # Check tournament status
    try:
        tournament_data = load_tournament_data()
        if tournament_data:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(CONFIG.bot.timezone)
            now = datetime.now(tz)

            registration_end = datetime.fromisoformat(tournament_data.get("registration_end", ""))
            if registration_end.tzinfo is None:
                registration_end = registration_end.replace(tzinfo=tz)

            tournament_end = datetime.fromisoformat(tournament_data.get("tournament_end", ""))
            if tournament_end.tzinfo is None:
                tournament_end = tournament_end.replace(tzinfo=tz)

            phase = tournament_data.get("phase", "unknown")
            teams_count = len(tournament_data.get("teams", {}))
            matches_count = len(tournament_data.get("matches", []))

            # Determine tournament state
            if phase == "registration":
                logger.info(f"[STARTUP] 🏆 Tournament: REGISTRATION phase ({teams_count} teams)")
            elif phase == "running":
                completed_matches = sum(1 for m in tournament_data.get("matches", []) if m.get("scheduled_time"))
                logger.info(f"[STARTUP] 🏆 Tournament: RUNNING ({completed_matches}/{matches_count} matches scheduled)")

                if now > tournament_end:
                    logger.warning(f"[STARTUP] ⚠️  Tournament end date has passed! ({tournament_end.strftime('%Y-%m-%d')})")
            elif phase == "finished":
                logger.info(f"[STARTUP] 🏆 Tournament: FINISHED ({matches_count} matches total)")
            else:
                logger.info(f"[STARTUP] 🏆 Tournament: Phase '{phase}'")
        else:
            logger.info("[STARTUP] ℹ️  No active tournament")
    except Exception as e:
        if DEBUG_MODE:
            logger.error(f"[STARTUP] ⚠️ Error checking tournament status: {e}")

    # Stop old tasks
    try:
        cancel_all_tasks()
        if DEBUG_MODE:
            logger.debug("[STARTUP] ✅ Old background tasks terminated")
    except Exception as e:
        logger.error(f"[STARTUP] ⚠️ Error terminating old tasks: {e}")

    # Start reminder system
    try:
        reminder_channel_id = CONFIG.get_channel_id("reminder")
        channel = bot.get_channel(reminder_channel_id)

        if channel:
            add_task("reminder_loop", bot.loop.create_task(match_reminder_loop(channel)))
            logger.info("[STARTUP] ✅ Reminder system started")
        else:
            logger.error(f"[STARTUP] ❌ Reminder channel (ID: {reminder_channel_id}) not found")
    except Exception as e:
        logger.error(f"[STARTUP] ❌ Failed to start reminder system: {e}")

    # Resync slash commands
    try:
        synced = await bot.tree.sync()
        if len(synced) == 0:
            logger.warning("[STARTUP] ⚠️ No slash commands synchronized")
        else:
            logger.info(f"[STARTUP] ✅ Slash commands synced ({len(synced)} commands)")
    except Exception as e:
        logger.error(f"[STARTUP] ❌ Slash command sync failed: {e}")

    logger.info("═" * 70)
    logger.info("[STARTUP] ✅ Bot initialization completed")
    logger.info("═" * 70 + "\n")


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
    logger.info("═" * 70)
    logger.info("[SYSTEM] 🚀 Initializing HeroldBot...")
    logger.info("═" * 70)

    # Track extension loading
    loaded_extensions = []
    failed_extensions = []

    # Load extensions/cogs
    for ext in EXTENSIONS:
        try:
            await bot.load_extension(ext)
            loaded_extensions.append(ext)
            if DEBUG_MODE:
                logger.debug(f"[SYSTEM] ✅ Extension loaded: {ext}")
        except Exception as e:
            failed_extensions.append(ext)
            logger.error(f"[SYSTEM] ❌ Error loading extension {ext}: {e}")

    # Summary of extension loading
    logger.info(f"[SYSTEM] ✅ Extensions: {len(loaded_extensions)}/{len(EXTENSIONS)} loaded successfully")
    if failed_extensions:
        logger.warning(f"[SYSTEM] ⚠️  Failed: {', '.join(failed_extensions)}")

    # Validate TOKEN before starting
    if not TOKEN:
        logger.critical("[SYSTEM] ❌ CRITICAL: Discord bot token not found! Check your .env file.")
        return

    # Start bot (blocks until the end)
    try:
        logger.info("[SYSTEM] 🔌 Connecting to Discord...")
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
