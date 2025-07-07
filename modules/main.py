# modules/main.py

import asyncio
import json
import os

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# Lokale Module
from modules import poll, tournament
from modules.dataStorage import (
    load_config,
    load_global_data,
    load_tournament_data,
    validate_channels,
    validate_permissions,
)
from modules.logger import logger
from modules.reminder import match_reminder_loop
from modules.task_manager import add_task, cancel_all_tasks, get_all_tasks

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
DEBUG_MODE = os.getenv("DEBUG") == "1"


def debug_dump_configs():
    """
    Gibt bei aktivem DEBUG-Modus die Konfigurationsdateien ins Log aus.
    """
    if not DEBUG_MODE:
        return

    logger.info("[DEBUG] Starte Dump der Konfigurations- und Datendateien...")

    try:
        with open("configs/config.json", "r", encoding="utf-8") as f:
            config_data = json.load(f)
        logger.info("[DEBUG] Inhalt von config.json:")
        logger.info(json.dumps(config_data, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.error(f"[DEBUG] Fehler beim Laden der config.json: {e}")

    try:
        global_data = load_global_data()
        logger.info("[DEBUG] Inhalt von data.json:")
        logger.info(json.dumps(global_data, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.error(f"[DEBUG] Fehler beim Laden der data.json: {e}")

    try:
        tournament_data = load_tournament_data()
        logger.info("[DEBUG] Inhalt von tournament.json:")
        logger.info(json.dumps(tournament_data, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.error(f"[DEBUG] Fehler beim Laden der tournament.json: {e}")

    logger.info("[DEBUG] Dump der Dateien abgeschlossen.")


TOKEN = os.getenv("DISCORD_TOKEN")

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
    # --- Startup-Checks ---
    tournament._registration_closed = False
    logger.info("[STARTUP] Flags: Aufgeräumt")

    try:
        cancel_all_tasks()
        logger.info("[STARTUP] Tasks: Canceled")
    except Exception as e:
        logger.warning(f"[STARTUP] Keine Tasks oder Fehler beim Cancelen: {e}")

    for folder in ["logs", "backups", "archive", "data", "langs", "configs"]:
        if not os.path.exists(folder):
            os.makedirs(folder)
            logger.info(f"[STARTUP] Verzeichnis angelegt: {folder}")
        else:
            logger.info(f"[STARTUP] Verzeichnis vorhanden: {folder}")

    required_files = ["data/data.json", "configs/config.json", "configs/names_de.json"]
    for f in required_files:
        if not os.path.exists(f):
            logger.error(f"[STARTUP] Notwendige Datei fehlt: {f}")
        else:
            try:
                with open(f, encoding="utf-8") as file:
                    json.load(file)
                logger.info(f"[STARTUP] Datei OK: {f}")
            except Exception as e:
                logger.error(f"[STARTUP] Datei beschädigt: {f} – {e}")

    # Check Channels
    await validate_channels(bot)
    # Check Permissions
    for guild in bot.guilds:
        await validate_permissions(guild)

    config = load_config()
    if not config.get("CHANNELS", {}):
        logger.error("[STARTUP] Keine CHANNELS in der Config!")

    # Reminder-Task starten
    try:
        reminder_channel_id = int(config.get("CHANNELS", {}).get("REMINDER", 0))
        channel = bot.get_channel(reminder_channel_id)
        if channel:
            add_task("reminder", asyncio.create_task(match_reminder_loop(channel)))
            logger.info(f"[STARTUP] Match-Reminder gestartet im Channel {channel.name}.")
        else:
            logger.error("[STARTUP] Reminder-Channel nicht gefunden oder ungültige ID!")
    except Exception as e:
        logger.error(f"[STARTUP] Fehler beim Starten des Reminder-Tasks: {e}")

    try:
        synced = await bot.tree.sync()
        debug_dump_configs()
        logger.info(f"[STARTUP] {len(synced)} Slash-Commands synchronisiert.")
    except Exception as e:
        logger.error(f"[STARTUP] Fehler beim Synchronisieren der Commands: {e}")

    logger.info("[STARTUP] STARTUP Checks abgeschlossen. Bot ist bereit.")


# ========== EXTENSIONS LADEN & BOT STARTEN ==========
async def main():
    # Extensions/Cogs laden
    for ext in EXTENSIONS:
        try:
            await bot.load_extension(ext)
            logger.info(f"[SYSTEM] Extension geladen: {ext}")
        except Exception as e:
            logger.error(f"[SYSTEM] Fehler beim Laden der Extension {ext}: {e}")

    # Bot starten (blockiert bis zum Ende)
    await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
