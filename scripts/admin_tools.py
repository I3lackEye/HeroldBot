import discord
from discord import app_commands, Interaction
from typing import Optional
from datetime import datetime
import random

from .dataStorage import load_global_data, save_global_data, load_tournament_data, save_tournament_data
from .utils import has_permission
from .logger import setup_logger

logger = setup_logger("logs")

# ----------------------------------------
# Admin-Hilfsfunktionen
# ----------------------------------------

async def force_sign_out(interaction: Interaction, user_mention: str):
    tournament = load_tournament_data()
    updated = False

    for team, team_entry in tournament.get("teams", {}).items():
        if user_mention in team_entry.get("members", []):
            del tournament["teams"][team]
            logger.info(f"[ADMIN] {user_mention} wurde aus Team '{team}' entfernt. Team aufgelöst.")

            other_members = [m for m in team_entry.get("members", []) if m != user_mention]
            if other_members:
                verfugbarkeit = team_entry.get("verfügbarkeit", "")
                tournament.setdefault("solo", []).append({"player": other_members[0], "verfügbarkeit": verfugbarkeit})
                logger.info(f"[ADMIN] {other_members[0]} wurde in die Solo-Liste übernommen mit Verfügbarkeit: {verfugbarkeit}")
            updated = True
            break

    if not updated:
        for entry in tournament.get("solo", []):
            if entry.get("player") == user_mention:
                tournament["solo"].remove(entry)
                logger.info(f"[ADMIN] {user_mention} wurde aus der Solo-Liste entfernt.")
                updated = True
                break

    if updated:
        save_tournament_data(tournament)
        await interaction.response.send_message(f"✅ {user_mention} wurde erfolgreich aus dem Turnier entfernt.", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠ {user_mention} ist weder in einem Team noch in der Solo-Liste registriert.", ephemeral=True)

# ----------------------------------------
# Admin Slash-Commands
# ----------------------------------------

@app_commands.command(name="admin_abmelden", description="Admin-Befehl: Entfernt einen Spieler aus dem Turnier.")
@app_commands.describe(user="Der Spieler, der entfernt werden soll.")
async def admin_abmelden(interaction: Interaction, user: discord.Member):
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
        return

    await force_sign_out(interaction, user.mention)

@app_commands.command(name="admin_add_win", description="Admin-Befehl: Vergibt manuell einen Sieg an einen Spieler.")
@app_commands.describe(user="Der Spieler, der den Sieg erhalten soll.")
async def admin_add_win(interaction: Interaction, user: discord.Member):
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
        return

    global_data = load_global_data()
    player_stats = global_data.setdefault("player_stats", {})

    user_id = str(user.id)
    if user_id not in player_stats:
        player_stats[user_id] = {"wins": 0, "name": user.mention}

    player_stats[user_id]["wins"] += 1
    save_global_data(global_data)

    await interaction.response.send_message(f"✅ {user.mention} wurde ein zusätzlicher Sieg gutgeschrieben.", ephemeral=True)
    logger.info(f"[ADMIN] {user.display_name} wurde manuell ein Sieg hinzugefügt.")

@app_commands.command(name="start_tournament", description="Admin-Befehl: Startet ein neues Turnier.")
async def start_tournament(interaction: Interaction):
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
        return

    tournament = {
        "solo": [],
        "teams": {},
        "poll_results": {},
        "registration_open": False,
        "running": True
    }
    save_tournament_data(tournament)
    await interaction.response.send_message("✅ Ein neues Turnier wurde gestartet!", ephemeral=False)
    logger.info("[ADMIN] Ein neues Turnier wurde gestartet.")

@app_commands.command(name="end_tournament", description="Admin-Befehl: Beendet das aktuelle Turnier.")
async def end_tournament(interaction: Interaction):
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
        return

    tournament = load_tournament_data()
    tournament["running"] = False
    save_tournament_data(tournament)
    await interaction.response.send_message("✅ Das Turnier wurde beendet!", ephemeral=False)
    logger.info("[ADMIN] Das Turnier wurde offiziell beendet.")

@app_commands.command(name="add_game", description="Admin-Befehl: Fügt ein neues Spiel zur Spielauswahl hinzu.")
@app_commands.describe(game="Name des Spiels, das hinzugefügt werden soll.")
async def add_game(interaction: Interaction, game: str):
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
        return

    global_data = load_global_data()
    games = global_data.setdefault("games", [])

    if game in games:
        await interaction.response.send_message("⚠ Dieses Spiel ist bereits in der Liste.", ephemeral=True)
        return

    games.append(game)
    save_global_data(global_data)
    await interaction.response.send_message(f"✅ Das Spiel **{game}** wurde hinzugefügt.", ephemeral=True)
    logger.info(f"[ADMIN] Spiel {game} zur Auswahl hinzugefügt.")

@app_commands.command(name="remove_game", description="Admin-Befehl: Entfernt ein Spiel aus der Spielauswahl.")
@app_commands.describe(game="Name des Spiels, das entfernt werden soll.")
async def remove_game(interaction: Interaction, game: str):
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
        return

    global_data = load_global_data()
    games = global_data.get("games", [])

    if game not in games:
        await interaction.response.send_message("⚠ Dieses Spiel wurde nicht gefunden.", ephemeral=True)
        return

    games.remove(game)
    save_global_data(global_data)
    await interaction.response.send_message(f"✅ Das Spiel **{game}** wurde entfernt.", ephemeral=True)
    logger.info(f"[ADMIN] Spiel {game} aus der Auswahl entfernt.")

@app_commands.command(name="award_overall_winner", description="Admin-Befehl: Trägt den Gesamtsieger des Turniers ein.")
@app_commands.describe(winning_team="Name des Gewinnerteams.", points="Erzielte Punkte.", game="Gespieltes Spiel.")
async def award_overall_winner(interaction: Interaction, winning_team: str, points: int, game: str):
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
        return

    global_data = load_global_data()
    global_data["last_tournament_winner"] = {
        "winning_team": winning_team,
        "points": points,
        "game": game,
        "ended_at": str(datetime.now())
    }
    save_global_data(global_data)
    await interaction.response.send_message(f"✅ Gesamtsieger **{winning_team}** mit {points} Punkten in {game} eingetragen!", ephemeral=False)
    logger.info(f"[ADMIN] Gesamtsieger {winning_team} eingetragen: {points} Punkte in {game}.")

