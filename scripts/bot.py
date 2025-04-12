import discord
from discord import app_commands
import os
import json
import logging
from typing import Optional, List
from .players import handle_sign_in, sign_out, list_participants
from .logger import setup_logger
from .tournament import start_tournament as tournament_start_poll
from .utils import has_permission, validate_string, remove_game_autocomplete
from .dataStorage import (
    load_tournament_data,
    save_tournament_data,
    load_global_data,
    save_global_data,
    init_file,
    load_config,
    CHANNEL_LIMIT_1,
    reset_tournament_data,
    DATA_FILE_PATH,
    DEFAULT_GLOBAL_DATA,
    TOURNAMENT_FILE_PATH,
    DEFAULT_TOURNAMENT_DATA,
    add_game_to_data,
    remove_game_from_data
)


# Konfiguration laden
config = load_config()
global_data = load_global_data()
tournament_data = load_tournament_data()
TOKEN = config.get("TOKEN")
permission = config.get("ROLE_PERMISSIONS")
debug = config.get("DEBUG")

# Logger init und Ausgabe
logger = setup_logger("logs", level=logging.INFO)
logger.info("🛈 Konfiguration geladen:")
logger.info(f"TOKEN: {TOKEN}")
logger.info(f"CHANNEL_LIMIT_1: {CHANNEL_LIMIT_1}")
logger.info(f"PERMISSIONS: {permission}")
logger.info(f"Tournament Data: {tournament_data}")
logger.info(f"DEBUG: {debug}")


# Erstelle den Bot und registriere Slash-Commands
intents = discord.Intents.default()
intents.members = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# Initialisiere die Dateien falls sie nicht existieren:
# Initialisiere die globale Datendatei (data.json), falls noch nicht vorhanden
init_file(DATA_FILE_PATH, DEFAULT_GLOBAL_DATA)
init_file(TOURNAMENT_FILE_PATH, DEFAULT_TOURNAMENT_DATA)

# Ausgabe zu Beginn des Bots (debug)
@bot.event
async def on_ready():
    await tree.sync()
    logger.info(f"{bot.user} ist online!")
    print(f"{bot.user} ist online!")

# Die angezeigten Slash-Commands
@tree.command(name="anmelden", description="Melde dich am Turnier an.")
async def anmelden(interaction: discord.Interaction,
                   mitspieler: Optional[discord.Member] = None,
                   teamname: Optional[str] = None):
    # Logik: Keine Parameter → Einzelanmeldung, beide Parameter → Teamanmeldung,
    # sonst Fehlermeldung.
    logger.info(f"Befehl 'anmelden' von {interaction.user} aufgerufen")
    await handle_sign_in(interaction, teamname, mitspieler, tournament_data, save_tournament_data)

@tree.command(name="abmelden", description="Melde dich von dem Turnier ab.")
async def abmelden(interaction: discord.Interaction):
    logger.info(f"Befehl 'abmelden' von {interaction.user} aufgerufen")
    await sign_out(interaction, tournament_data, save_tournament_data)

@tree.command(name="teilnehmer", description="Zeigt die aktuelle Teilnehmerliste an.")
async def teilnehmer(interaction: discord.Interaction):
    participant_text = await list_participants(interaction, tournament_data)
    logger.info(f"Befehl 'teilnehmer' von {interaction.user} aufgerufen")
    await interaction.response.send_message(participant_text, ephemeral=False)

@tree.command(name="start_tournament", description="Starte ein neues Turnier Optional: Registrierungsdauer in Tagen angeben.")
async def start_tournament(interaction: discord.Interaction, duration_days: Optional[float] = None):
    """
    Startet ein neues Turnier.
    :param duration_days: (Optional) Registrierungsdauer in Tagen. Standard ist 7 Tage.
    """
    # Standarddauer in Tagen
    if duration_days is None:
        duration_days = 7.0

    # Umrechnen in Sekunden
    registration_seconds = int(duration_days * 86400)
    
    # Den Tournament-Workflow in tournament.py aufrufen und die Registrierungsdauer übergeben
    await tournament_start_poll(interaction, registration_seconds)

@tree.command(name="add_game", description="Fügt ein neues Spiel zum globalen Datensatz hinzu.")
async def add_game(interaction: discord.Interaction, title: str):
    logger.info(f"Befehl 'add_game' von {interaction.user} aufgerufen")

    if interaction.channel_id != CHANNEL_LIMIT_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        logger.info(f"User {interaction.user} hat falschen Channel für Command verwendet")
        return

    # Eingabe validieren: nur erlaubte Zeichen und max. Länge 50
    is_valid, error_message = validate_string(title)
    if not is_valid:
        await interaction.response.send_message(error_message, ephemeral=True)
        return

    if not has_permission(interaction.user, "Moderator", "Admin"):
        logger.info(f"{interaction.user} hatte keine Berechtigung")
        await interaction.response.send_message("Du hast keine ausreichenden Rechte, um diesen Befehl auszuführen.", ephemeral=True)
        return

    try:
        add_game_to_data(title)
    except ValueError as e:
        await interaction.response.send_message(str(e), ephemeral=True)
        return

    logger.info(f"Befehl 'add_game' von {interaction.user} aufgerufen")
    await interaction.response.send_message(f"Das Spiel '{title}' wurde erfolgreich hinzugefügt.", ephemeral=True)

@tree.command(name="remove_game", description="Entfernt ein Spiel aus dem globalen Datensatz.")
async def remove_game(interaction: discord.Interaction, title: str):
    logger.info(f"Befehl 'remove_game' von {interaction.user} aufgerufen")
    
    if interaction.channel_id != CHANNEL_LIMIT_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        logger.info(f"User {interaction.user} hat falschen Channel für Command verwendet")
        return

    is_valid, error_message = validate_string(title)
    if not is_valid:
        await interaction.response.send_message(error_message, ephemeral=True)
        return

    if not has_permission(interaction.user, "Moderator", "Admin"):
        logger.info(f"{interaction.user} hatte keine Berechtigung")
        await interaction.response.send_message("Du hast keine ausreichenden Rechte, um diesen Befehl auszuführen.", ephemeral=True)
        return

    # Hier kommt die Logik zum Entfernen des Spiels
    try:
        remove_game_from_data(title)
    except ValueError as e:
        await interaction.response.send_message(str(e), ephemeral=True)
        return

    await interaction.response.send_message(f"Das Spiel '{title}' wurde erfolgreich entfernt.", ephemeral=True)

# Autocomplete Funktion für das löschen von Spielen
@remove_game.autocomplete("title")
async def remove_game_title_autocomplete(interaction: discord.Interaction, current: str):
    return await remove_game_autocomplete(interaction, current)

# Start des eigentlichen Bots
bot.run(TOKEN)
