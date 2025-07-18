# modules/main.py

import asyncio
import json
import os

import discord
from discord import app_commands
from discord.ext import commands

# Lokale Module
from modules import poll, tournament, task_manager
from modules.dataStorage import (
    DEBUG_MODE,
    TOKEN,
    load_config,
    load_global_data,
    load_tournament_data,
    validate_channels,
    validate_permissions,
    load_env
)
from modules.logger import logger
from modules.reminder import match_reminder_loop
from modules.task_manager import add_task, cancel_all_tasks, get_all_tasks

#Wichtig
load_env()


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
    config = load_config()
    language = str(config.get("language", "de")).lower()

    logger.info(f"[STARTUP] Bot ist online als {bot.user.name} (ID: {bot.user.id})")
    logger.info(f"[STARTUP] Sprache aus config.json: {language}")
    logger.info(f"[STARTUP] DEBUG-Modus: {'aktiv' if DEBUG_MODE else 'inaktiv'}")

    # Wichtige Ordner prüfen
    startup_folders = [
        "logs", "backups", "archive", "data", "locale", "configs",
        os.path.join("locale", language, "embeds")
    ]

    for folder in startup_folders:
        if not os.path.exists(folder):
            try:
                os.makedirs(folder)
                logger.info(f"[STARTUP] Ordner erstellt: {folder}")
            except Exception as e:
                logger.error(f"[STARTUP] Fehler beim Erstellen von {folder}: {e}")
        else:
            logger.info(f"[STARTUP] Ordner vorhanden: {folder}")

    # Essenzielle Dateien prüfen
    required_files = [
        "configs/config.json",
        "data/data.json",
        "data/tournament.json",
        "data/games.json",
        f"locale/{language}/names_{language}.json",
    ]

    logger.info("[STARTUP] Datei-Validierung beginnt...")
    for path in required_files:
        if not os.path.exists(path):
            logger.error(f"[STARTUP] ❌ Datei fehlt: {path}")
        else:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    json.load(f)
                logger.info(f"[STARTUP] Datei OK: {path}")
            except Exception as e:
                logger.error(f"[STARTUP] ❌ Fehler beim Parsen von {path}: {e}")
    logger.info("[STARTUP] Datei-Validierung abgeschlossen.")

    # Alte Tasks beenden
    task_manager.cancel_all_tasks()
    logger.info("[STARTUP] Alte Hintergrund-Tasks beendet.")

    # Reminder-Channel aus der Config holen
    reminder_channel_id = int(config.get("CHANNELS", {}).get("REMINDER", 0))
    channel = bot.get_channel(reminder_channel_id)

    if channel:
        task_manager.add_task("reminder_loop", bot.loop.create_task(match_reminder_loop(channel)))
        logger.info("[STARTUP] Reminder Subsystem gestartet")
    else:
        logger.error(f"[REMINDER] ❌ Reminder-Channel mit ID {reminder_channel_id} nicht gefunden!")


    # Slash-Commands neu synchronisieren
    try:
        synced = await bot.tree.sync()
        if len(synced) == 0:
            logger.warning("[STARTUP] ⚠️ Keine Slash-Commands synchronisiert.")
        else:
            logger.info(f"[STARTUP] Slash-Commands synchronisiert ({len(synced)} Befehle).")
    except Exception as e:
        logger.error(f"[STARTUP] ❌ Slash-Command-Sync fehlgeschlagen: {e}")

    logger.info("[STARTUP] ✅ Initialisierung abgeschlossen.\n")


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
