# modules/main.py

import asyncio
import json
import os

import discord
from discord import app_commands
from discord.ext import commands

# Local modules
from modules import poll, tournament, task_manager
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
from modules.task_manager import add_task, cancel_all_tasks, get_all_tasks

# Important
load_env()


def debug_dump_configs():
    """
    Outputs configuration files to the log when DEBUG mode is active.
    """
    if not DEBUG_MODE:
        return

    logger.info("[DEBUG] Starting dump of configuration and data files...")

    # Dump bot config
    try:
        with open("configs/bot.json", "r", encoding="utf-8") as f:
            bot_config = json.load(f)
        logger.info("[DEBUG] Content of configs/bot.json:")
        logger.info(json.dumps(bot_config, indent=2, ensure_ascii=False))
    except (FileNotFoundError, json.JSONDecodeError, IOError) as e:
        logger.error(f"[DEBUG] Error loading bot.json: {e}")

    # Dump tournament config
    try:
        with open("configs/tournament.json", "r", encoding="utf-8") as f:
            tournament_config = json.load(f)
        logger.info("[DEBUG] Content of configs/tournament.json:")
        logger.info(json.dumps(tournament_config, indent=2, ensure_ascii=False))
    except (FileNotFoundError, json.JSONDecodeError, IOError) as e:
        logger.error(f"[DEBUG] Error loading tournament.json: {e}")

    # Dump features config
    try:
        with open("configs/features.json", "r", encoding="utf-8") as f:
            features_config = json.load(f)
        logger.info("[DEBUG] Content of configs/features.json:")
        logger.info(json.dumps(features_config, indent=2, ensure_ascii=False))
    except (FileNotFoundError, json.JSONDecodeError, IOError) as e:
        logger.error(f"[DEBUG] Error loading features.json: {e}")

    # Dump data files
    try:
        global_data = load_global_data()
        logger.info("[DEBUG] Content of data.json:")
        logger.info(json.dumps(global_data, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.error(f"[DEBUG] Error loading data.json: {e}")

    try:
        tournament_data = load_tournament_data()
        logger.info("[DEBUG] Content of tournament.json:")
        logger.info(json.dumps(tournament_data, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.error(f"[DEBUG] Error loading tournament.json: {e}")

    logger.info("[DEBUG] File dump completed.")


intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

EXTENSIONS = [
    "modules.players",
    "modules.tournament",
    "modules.info",
    "modules.admin_tools",
    "modules.dev_tools",
    "modules.stats",
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
        "configs/config.json",
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
                logger.info(f"[STARTUP] File OK: {path}")
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"[STARTUP] ❌ Error parsing {path}: {e}")
    logger.info("[STARTUP] File validation completed.")

    # Stop old tasks
    task_manager.cancel_all_tasks()
    logger.info("[STARTUP] Old background tasks terminated.")

    # Get reminder channel from config
    reminder_channel_id = int(config.get("CHANNELS", {}).get("REMINDER", 0))
    channel = bot.get_channel(reminder_channel_id)

    if channel:
        task_manager.add_task("reminder_loop", bot.loop.create_task(match_reminder_loop(channel)))
        logger.info("[STARTUP] Reminder subsystem started")
    else:
        logger.error(f"[REMINDER] ❌ Reminder channel with ID {reminder_channel_id} not found!")


    # Resync slash commands
    try:
        synced = await bot.tree.sync()
        if len(synced) == 0:
            logger.warning("[STARTUP] ⚠️ No slash commands synchronized.")
        else:
            logger.info(f"[STARTUP] Slash commands synchronized ({len(synced)} commands).")
    except Exception as e:
        logger.error(f"[STARTUP] ❌ Slash command sync failed: {e}")

    logger.info("[STARTUP] ✅ Initialization completed.\n")


# ========== LOAD EXTENSIONS & START BOT ==========
async def main():
    # Load extensions/cogs
    for ext in EXTENSIONS:
        try:
            await bot.load_extension(ext)
            logger.info(f"[SYSTEM] Extension loaded: {ext}")
        except Exception as e:
            logger.error(f"[SYSTEM] Error loading extension {ext}: {e}")

    # Start bot (blocks until the end)
    await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
