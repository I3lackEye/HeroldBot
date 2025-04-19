import discord
import json
import os
from discord import app_commands
from discord.ext import commands
from discord.ext import tasks
from dotenv import load_dotenv


# Lokale Module
from modules.dataStorage import load_global_data, load_tournament_data, load_config
from modules.logger import logger
from modules.reminder import match_reminder_loop
from modules.reschedule import request_reschedule
from modules.players import anmelden, update_availability, sign_out, participants, help_command
from modules.tournament import (
    start_tournament,
    close_registration_after_delay,
    close_tournament_after_delay,
    end_tournament,
    list_matches,
    match_schedule
)
from .admin_tools import (
    report_match,
    force_sign_out,
    admin_abmelden,
    admin_add_win,
    add_game,
    remove_game,
    award_overall_winner,
    reload_commands,
    close_registration,
    generate_dummy_teams,
    test_reminder,
    archive_tournament
)
from .stats import (
    team_stats,
    leaderboard,
    stats,
    tournament_stats,
    match_history,
    status
)

# Globale Variable für Task-Handling
reminder_task = None  

# Lade Umgebungsvariablen
load_dotenv()

# Debug-Modus lesen
DEBUG_MODE = os.getenv("DEBUG") == "1"

# Debug Ausgabe 
def debug_dump_configs():
    """
    Gibt bei aktivem DEBUG-Modus die Konfigurationsdateien ins Log aus.
    """
    if not DEBUG_MODE:
        return

    logger.info("[DEBUG] Starte Dump der Konfigurations- und Datendateien...")

    try:
        with open("config.json", "r", encoding="utf-8") as f:
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
tree = bot.tree

@bot.event
async def on_ready():
    global reminder_task

    logger.info(f"✅ Bot ist eingeloggt als {bot.user}")
    try:
        synced = await tree.sync()
        debug_dump_configs()
        logger.info(f"🔄 {len(synced)} Slash-Commands synchronisiert.")
    except Exception as e:
        print(f"❌ Fehler beim Synchronisieren der Commands: {e}")

    # Reminder-Task starten
    if reminder_task is None or reminder_task.done():
        config = load_config()
        reminder_channel_id = int(config.get("CHANNELS", {}).get("REMINDER", 0))
        channel = bot.get_channel(reminder_channel_id)
        
        if channel:
            reminder_task = bot.loop.create_task(match_reminder_loop(channel))
            logger.info(f"🔔 Match-Reminder gestartet im Channel {channel.name}.")
        else:
            logger.error("❌ Reminder-Channel nicht gefunden oder ungültige ID!")
    else:
        logger.info("ℹ️ Reminder-Task läuft bereits.")

# --------------------------------
# Slash-Commands Registrieren
# --------------------------------

# Spielerbefehle
tree.add_command(anmelden)
tree.add_command(update_availability)
tree.add_command(sign_out)
tree.add_command(participants)
tree.add_command(help_command)
tree.add_command(list_matches)
tree.add_command(request_reschedule)
tree.add_command(test_reminder)

# Statistikbefehle
tree.add_command(leaderboard)
tree.add_command(stats)
tree.add_command(tournament_stats)
tree.add_command(status)

# Turnierbefehle
tree.add_command(report_match)
tree.add_command(match_history)
tree.add_command(team_stats)
tree.add_command(match_schedule)

# Adminbefehle
tree.add_command(admin_abmelden)
tree.add_command(admin_add_win)
tree.add_command(start_tournament)
tree.add_command(end_tournament)
tree.add_command(add_game)
tree.add_command(remove_game)
tree.add_command(award_overall_winner)
tree.add_command(reload_commands)
tree.add_command(close_registration)
tree.add_command(generate_dummy_teams)
tree.add_command(archive_tournament)

# --------------------------------
# Bot starten
# --------------------------------

bot.run(TOKEN)
