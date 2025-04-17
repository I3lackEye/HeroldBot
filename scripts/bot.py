import discord
import json
import os
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


# Lokale Module
from .dataStorage import load_global_data, load_tournament_data
from .logger import setup_logger
from .players import anmelden, update_availability, sign_out_command, participants
from .stats import leaderboard, stats, tournament_stats
from .tournament import (
    report_match,
    list_matches,
    match_history,
    team_stats,
    set_winner_command,
    close_registration
)
from .admin_tools import (
    admin_abmelden,
    admin_add_win,
    start_tournament,
    end_tournament,
    add_game,
    remove_game,
    award_overall_winner
)

# Setup Logger
logger = setup_logger("logs")

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
    print(f"✅ Bot ist eingeloggt als {bot.user}")
    try:
        synced = await tree.sync()
        debug_dump_configs()
        print(f"🔄 {len(synced)} Slash-Commands synchronisiert.")
    except Exception as e:
        print(f"❌ Fehler beim Synchronisieren der Commands: {e}")

# --------------------------------
# Slash-Commands Registrieren
# --------------------------------

# Spielerbefehle
tree.add_command(anmelden)
tree.add_command(update_availability)
tree.add_command(sign_out_command)
tree.add_command(participants)

# Statistikbefehle
tree.add_command(leaderboard)
tree.add_command(stats)
tree.add_command(tournament_stats)

# Turnierbefehle
tree.add_command(report_match)
tree.add_command(list_matches)
tree.add_command(match_history)
tree.add_command(team_stats)

# Adminbefehle
tree.add_command(admin_abmelden)
tree.add_command(admin_add_win)
tree.add_command(start_tournament)
tree.add_command(end_tournament)
tree.add_command(add_game)
tree.add_command(remove_game)
tree.add_command(award_overall_winner)

# --------------------------------
# Bot starten
# --------------------------------

bot.run(TOKEN)
