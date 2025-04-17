import discord
from discord import app_commands
import os
import json
import logging
from typing import Optional, List
from .logger import setup_logger
from .stats import build_stats_embed, build_leaderboard_embed
from .utils import(
    has_permission,
    validate_string,
    remove_game_autocomplete,
    get_tournament_status,
    add_manual_win
)
from .tournament import (
    start_tournament as tournament_start_poll,
    set_winner as tournament_set_winner,
    end_tournament,
    get_overall_winner,
    send_tournament_announcement,
    send_tournament_end_announcement
)
from .players import (
    handle_sign_in, 
    sign_out, 
    list_participants, 
    update_availability_function,
    get_leaderboard,
    force_sign_out
)
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

# ---Die angezeigten Slash-Commands---

# -Spieler Befehle-
@tree.command(name="anmelden", description="Melde dich am Turnier an.")
@app_commands.describe(
    verfugbarkeit="Gib deinen Verfügbarkeitszeitraum im Format HH:MM-HH:MM an (z.B. 12:00-18:00).",
    mitspieler="Optional: Gib den Mitspieler an, falls du als Team spielst.",
    teamname="Optional: Teamname (muss zusammen mit 'mitspieler' angegeben werden)."
)
async def anmelden(interaction: discord.Interaction, 
                    verfugbarkeit: str, 
                    mitspieler: Optional[discord.Member] = None, 
                    teamname: Optional[str] = None):
    """
    Meldet den Nutzer entweder als Solo oder als Team an. 
    Der Verfügbarkeitszeitraum ist verpflichtend anzugeben.
    """
    logger.info(f"Befehl 'anmelden' von {interaction.user} aufgerufen")
    await handle_sign_in(interaction, teamname, mitspieler, tournament_data, verfugbarkeit)

@tree.command(name="update_availability", description="Aktualisiere deinen Verfügbarkeitszeitraum (Format: HH:MM-HH:MM).")
@app_commands.describe(verfugbarkeit="Gib deinen Verfügbarkeitszeitraum im Format HH:MM-HH:MM an (z.B. 12:00-18:00).")
async def update_availability(interaction: discord.Interaction, verfugbarkeit: str):
    await update_availability_function(interaction, verfugbarkeit)

@tree.command(name="sign_out", description="Melde dich vom Turnier ab.")
async def sign_out_command(interaction: discord.Interaction):
    await sign_out(interaction)

@tree.command(name="participants", description="Zeigt die aktuellen Anmeldungen.")
async def participants(interaction: discord.Interaction):
    await list_participants(interaction)
    
@tree.command(name="status", description="Zeigt den aktuellen Status des Turniers.")
async def status(interaction: discord.Interaction):
    status_message = get_tournament_status()
    await interaction.response.send_message(status_message, ephemeral=False)

@tree.command(name="leaderboard", description="Zeigt das Turnier-Leaderboard mit den meisten Siegen.")
async def leaderboard(interaction: discord.Interaction):
    data = load_global_data()
    stats_data = data.get("player_stats", {})

    if not stats_data:
        await interaction.response.send_message("❌ Es sind noch keine Spielerdaten vorhanden.", ephemeral=True)
        return

    embed = build_leaderboard_embed(stats_data)
    await interaction.response.send_message(embed=embed)

@tree.command(name="stats", description="Zeigt die Turnierstatistiken eines Spielers.")
@app_commands.describe(user="Der Spieler, dessen Statistiken angezeigt werden sollen.")
async def stats(interaction: discord.Interaction, user: discord.Member):
    data = load_global_data()
    user_id = str(user.id)
    stats_data = data.get("player_stats", {}).get(user_id)

    if not stats_data:
        await interaction.response.send_message(f"📭 {user.mention} hat bisher keine Turnierstatistiken.", ephemeral=True)
        return

    embed = build_stats_embed(user, stats_data)
    await interaction.response.send_message(embed=embed)

@tree.command(name="tournament_stats", description="Zeigt allgemeine Turnierstatistiken.")
async def tournament_stats(interaction: discord.Interaction):
    stats_message = get_global_tournament_stats()
    await interaction.response.send_message(stats_message)

# -Adminbefehle-

@tree.command(name="start_tournament", description="Starte ein neues Turnier Optional: Registrierungsdauer in Tagen angeben.")
async def start_tournament(interaction: discord.Interaction, duration_days: Optional[float] = None):
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("Du hast keine Berechtigung, diesen Befehl auszuführen.", ephemeral=True)
        return

    if duration_days is None:
        duration_days = 7.0
    registration_seconds = int(duration_days * 86400)

    await send_tournament_announcement(interaction, registration_seconds)
    await tournament_start_poll(interaction, registration_seconds)
    
@tree.command(name="close_registration", description="Beendet manuell die Anmeldefrist und triggert den Matchmaker (Debug).")
async def close_registration(interaction: discord.Interaction):
    # Berechtigungscheck (nur Administratoren dürfen diesen Debug-Befehl ausführen)
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("Du hast keine Berechtigung, diesen Befehl auszuführen.", ephemeral=True)
        return

    # Lade die aktuellen Turnier-Daten
    tournament = load_tournament_data()
    # Setze die Registrierungsphase auf geschlossen
    tournament["registration_open"] = False
    save_tournament_data(tournament)
    await interaction.channel.send("Die Anmeldefrist wurde manuell beendet.")

    # Jetzt den Matchmaker ausführen:
    from .matchmaker import run_matchmaker  # Importiere die Matchmaker-Funktion aus deiner matchmaker.py
    schedule = run_matchmaker()
    
    # Erstelle eine Meldung mit dem Spielplan
    if schedule:
        msg_lines = ["**Spielplan für Round-Robin-Matches:**"]
        for match in schedule:
            msg_lines.append(f"{match['date']} um {match['start_time']}: {match['team1']} vs. {match['team2']}")
        plan_message = "\n".join(msg_lines)
    else:
        plan_message = "Es konnten keine Matches generiert werden (nicht genügend Teams mit Verfügbarkeitsangaben)."
    
    await interaction.channel.send(plan_message)
    await interaction.response.send_message("Matchmaker wurde getriggert.", ephemeral=True)

@tree.command(name="set_winner", description="Setzt den Gewinner eines Matches (Admin).")
async def set_winner_command(interaction: discord.Interaction, team: str):
    # Berechtigungsprüfung: Nur Admins dürfen diesen Command ausführen.
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("Du hast keine Berechtigung, diesen Befehl auszuführen.", ephemeral=True)
        return
    await tournament_set_winner(interaction, team)

@set_winner_command.autocomplete("team")
async def set_winner_team_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    tournament = load_tournament_data()
    teams = tournament.get("teams", {})
    return [
        app_commands.Choice(name=team_name, value=team_name)
        for team_name in teams.keys() if current.lower() in team_name.lower()
    ]

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

    await interaction.response.send_message(f"Das Spiel '{title}' wurde erfolgreich hinzugefügt.", ephemeral=True)

@tree.command(name="end_tournament", description="Beendet ein Turnier und zeichnet den Gewinner aus.")
@app_commands.describe(
    teamname="Name des Siegerteams",
    player1="Erster Spieler des Siegerteams",
    player2="Zweiter Spieler des Siegerteams (optional)",
    points="Anzahl Punkte, die vergeben werden (Standard: 1)"
)
async def end_tournament(
    interaction: discord.Interaction,
    teamname: str,
    player1: discord.Member,
    player2: Optional[discord.Member] = None,
    points: int = 1
):
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
        return

    tournament = load_tournament_data()
    game = tournament.get("game", "Unbekanntes Spiel")

    winner_ids = [player1.id]
    if player2:
        winner_ids.append(player2.id)

    # 🧠 Stats speichern
    finalize_tournament(teamname, winner_ids, game, points)

    # 📣 Embed anzeigen
    await send_tournament_end_announcement(interaction, teamname, points, game)

    await interaction.response.send_message("✅ Turnier wurde erfolgreich beendet und gespeichert.", ephemeral=True)

@tree.command(name="award_overall_winner", description="Weist dem turnierübergreifenden Gewinner die Siegerrolle zu (Admin).")
async def award_overall_winner_command(interaction: discord.Interaction):
    logger.info(f"Befehl 'award_overall_winner' von {interaction.user} aufgerufen")
    if interaction.channel_id != CHANNEL_LIMIT_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        logger.info(f"User {interaction.user} hat falschen Channel für Command verwendet")
        return

    if not has_permission(interaction.user, "Moderator", "Admin"):
        logger.info(f"{interaction.user} hatte keine Berechtigung")
        await interaction.response.send_message("Du hast keine ausreichenden Rechte, um diesen Befehl auszuführen.", ephemeral=True)
        return

    overall_winner, wins = get_overall_winner()  # Kein Parameter
    overall_winner = f"<@{overall_winner}>"
    # Hier kannst du dann die gewonnene Information weiterverwenden, z.B. Rolle vergeben:
    await interaction.response.send_message(f"Der turnierübergreifende Gewinner ist: {overall_winner} mit {wins} Siegen.", ephemeral=True)

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

@remove_game.autocomplete("title")
async def remove_game_title_autocomplete(interaction: discord.Interaction, current: str):
    return await remove_game_autocomplete(interaction, current)

@tree.command(name="admin_abmelden", description="Admin-Befehl: Entfernt einen Spieler aus dem Turnier.")
@app_commands.describe(user="Der Spieler, der entfernt werden soll.")
async def admin_abmelden(interaction: discord.Interaction, user: str):
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
        return

    await force_sign_out(interaction, user)

@admin_abmelden.autocomplete("user")
async def admin_abmelden_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    tournament = load_tournament_data()
    choices = set()

    # Solo-Spieler
    for entry in tournament.get("solo", []):
        name = entry.get("player", "")
        if current.lower() in name.lower():
            choices.add(name)

    # Team-Mitglieder
    for team_data in tournament.get("teams", {}).values():
        for member in team_data.get("members", []):
            if current.lower() in member.lower():
                choices.add(member)

    return [app_commands.Choice(name=name, value=name) for name in sorted(choices)][:25]

@tree.command(name="admin_add_win", description="(Admin) Vergibt manuell einen Sieg an einen Spieler.")
@app_commands.describe(user="Der Spieler, dem ein Sieg hinzugefügt werden soll.")
async def admin_add_win(interaction: discord.Interaction, user: discord.Member):
    if not has_permission(interaction.user, "Admin", "Moderator"):
        await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Debug-Befehl.", ephemeral=True)
        return

    add_manual_win(user.id)
    await interaction.response.send_message(f"✅ {user.mention} wurde manuell ein Sieg gutgeschrieben.", ephemeral=True)

# Start des eigentlichen Bots
bot.run(TOKEN)
