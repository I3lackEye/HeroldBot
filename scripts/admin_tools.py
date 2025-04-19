import discord
from discord import app_commands, Interaction
from typing import Optional
from datetime import datetime
import random
from random import randint, choice


# Lokale Module
from .dataStorage import load_global_data, save_global_data, load_tournament_data, save_tournament_data, load_config
from .utils import has_permission, generate_team_name, smart_send, generate_random_availability, parse_availability
from .logger import setup_logger
from .stats import autocomplete_players, autocomplete_teams
from .matchmaker import auto_match_solo, create_round_robin_schedule, assign_matches_to_slots, generate_schedule_overview, cleanup_orphan_teams
from .embeds import send_match_schedule_embed, create_embed_from_config

logger = setup_logger("logs")

# ----------------------------------------
# Admin-Hilfsfunktionen
# ----------------------------------------

async def force_sign_out(interaction: Interaction, user_mention: str):
    tournament = load_tournament_data()
    updated = False

    user_mention = interaction.user.mention
    user_name = interaction.user.display_name

    for team, team_entry in tournament.get("teams", {}).items():
        if user_mention in team_entry.get("members", []):
            del tournament["teams"][team]
            logger.info(f"[ADMIN] {user_mention} wurde aus Team '{team}' entfernt. Team aufgelöst.")

            other_members = [m for m in team_entry.get("members", []) if m != user_mention]
            if other_members:
                verfugbarkeit = team_entry.get("verfügbarkeit", "")
                tournament.setdefault("solo", []).append({"player": other_members[0], "verfügbarkeit": verfugbarkeit})
                logger.info(f"[ADMIN] {user_name} wurde in die Solo-Liste übernommen mit Verfügbarkeit: {verfugbarkeit}")
            updated = True
            break

    if not updated:
        for entry in tournament.get("solo", []):
            if entry.get("player") == user_mention:
                tournament["solo"].remove(entry)
                logger.info(f"[ADMIN] {user_name} wurde aus der Solo-Liste entfernt.")
                updated = True
                break

    if updated:
        save_tournament_data(tournament)
        await interaction.response.send_message(f"✅ {user_name} wurde erfolgreich aus dem Turnier entfernt.", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠ {user_name} ist weder in einem Team noch in der Solo-Liste registriert.", ephemeral=True)

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

@app_commands.command(name="admin_add_win", description="Admin-Befehl: Vergibt manuell einen Turniersieg an einen Spieler.")
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
@app_commands.autocomplete(winning_team=autocomplete_teams)
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

@app_commands.command(name="report_match", description="Trage das Ergebnis eines Matches ein.")
@app_commands.describe(team="Dein Teamname", opponent="Gegnerischer Teamname", result="Ergebnis auswählen")
@app_commands.autocomplete(team=autocomplete_teams, opponent=autocomplete_teams)
async def report_match(interaction: Interaction, team: str, opponent: str, result: str):
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
        return
    """
    Ermöglicht das Eintragen eines Match-Ergebnisses für ein Turnierspiel.
    """
    tournament = load_tournament_data()
    matches = tournament.get("matches", [])

    # Validierungen
    if team == opponent:
        await interaction.response.send_message("🚫 Du kannst nicht gegen dein eigenes Team spielen!", ephemeral=True)
        return

    if result.lower() not in ["win", "loss"]:
        await interaction.response.send_message("🚫 Ungültiges Ergebnis. Bitte gib **win** oder **loss** an.", ephemeral=True)
        return

    # Match speichern
    match_entry = {
        "team": team,
        "opponent": opponent,
        "result": result.lower(),
        "timestamp": datetime.now().isoformat()
    }
    matches.append(match_entry)
    tournament["matches"] = matches
    save_tournament_data(tournament)

    await interaction.response.send_message(
        f"✅ Ergebnis gespeichert:\n\n**{team}** vs **{opponent}**\n➔ Ergebnis: **{result.upper()}**",
        ephemeral=True
    )

    logger.info(f"[MATCH REPORT] {team} vs {opponent} – Ergebnis: {result.lower()}")

@app_commands.command(name="reload", description="Synchronisiert alle Slash-Commands neu.")
async def reload_commands(interaction: Interaction):
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
        return
    
    await interaction.response.send_message("🔄 Synchronisiere Slash-Commands...", ephemeral=True)

    try:
        synced = await interaction.client.tree.sync()
        await interaction.edit_original_response(content=f"✅ {len(synced)} Slash-Commands wurden neu geladen.")
        logger.info(f"[RELOAD] {len(synced)} Slash-Commands neu geladen von {interaction.user.display_name}")
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Fehler beim Neuladen: {e}")
        logger.error(f"[RELOAD ERROR] {e}")

@app_commands.command(name="close_registration", description="(Admin) Schließt die Anmeldung und startet die Matchgenerierung.")
async def close_registration(interaction: Interaction):
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("🚫 Du hast keine Berechtigung.", ephemeral=True)
        return

    tournament = load_tournament_data()

    if not tournament.get("running", False) or not tournament.get("registration_open", False):
        await interaction.response.send_message("⚠️ Die Anmeldung ist bereits geschlossen oder es läuft kein Turnier.", ephemeral=True)
        return

    # Schritt 1: Anmeldung schließen
    tournament["registration_open"] = False
    save_tournament_data(tournament)

    await smart_send(interaction, content="🚫 **Die Anmeldung wurde geschlossen.**")
    logger.info("[TOURNAMENT] Anmeldung manuell geschlossen.")

    # Schritt 2: Verwaiste Teams aufräumen
    await cleanup_orphan_teams(interaction.channel)

    # Schritt 3: Solo-Spieler automatisch matchen
    auto_match_solo()

    # Schritt 4: Matchplan erstellen
    create_round_robin_schedule()

    # Schritt 5: Matches auf Slots verteilen
    await assign_matches_to_slots()

    # Schritt 6: Überblick posten
    description_text = generate_schedule_overview()
    await send_match_schedule_embed(interaction, description_text)

@app_commands.command(name="generate_dummy", description="(Admin) Erzeugt Dummy-Solos und Dummy-Teams zum Testen.")
@app_commands.describe(num_solo="Anzahl Solo-Spieler", num_teams="Anzahl Teams")
async def generate_dummy_teams(interaction: Interaction, num_solo: int = 4, num_teams: int = 2):
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("🚫 Du hast keine Berechtigung dafür.", ephemeral=True)
        return

    tournament = load_tournament_data()

    # Solo-Spieler erzeugen
    solo_players = []
    for i in range(num_solo):
        player_name = f"DummySolo_{i+1}"
        availability, special = generate_random_availability()

        player_entry = {
            "player": player_name,
            "verfügbarkeit": availability
        }
        if special:
            player_entry.update(special)

        solo_players.append(player_entry)

    tournament.setdefault("solo", []).extend(solo_players)

    # Teams erzeugen
    teams = tournament.setdefault("teams", {})
    for i in range(num_teams):
        team_name = f"DummyTeam_{i+1}"
        member1 = f"TeamMember_{i+1}_1"
        member2 = f"TeamMember_{i+1}_2"
        availability, special = generate_random_availability()

        team_entry = {
            "members": [member1, member2],
            "verfügbarkeit": availability
        }
        if special:
            team_entry.update(special)

        teams[team_name] = team_entry

    save_tournament_data(tournament)

    logger.info(f"[DUMMY] {num_solo} Solo-Spieler und {num_teams} Teams erstellt.")
    await interaction.response.send_message(f"✅ {num_solo} Solo-Spieler und {num_teams} Teams wurden erfolgreich erzeugt!", ephemeral=True)

import random
from discord import app_commands, Interaction

@app_commands.command(name="test_reminder", description="Testet ein Reminder-Embed mit einem zufälligen Match.")
async def test_reminder(interaction: Interaction):
    config = load_config()
    reminder_channel_id = int(config.get("CHANNELS", {}).get("REMINDER", 0))

    guild = interaction.guild
    if not guild:
        await smart_send(interaction, content="🚫 Dieser Befehl kann nur auf einem Server genutzt werden.", ephemeral=True)
        return

    channel = guild.get_channel(reminder_channel_id)
    if not channel:
        await smart_send(interaction, content="🚫 Reminder-Channel nicht gefunden! Bitte überprüfe die Config.", ephemeral=True)
        return

    tournament = load_tournament_data()
    matches = tournament.get("matches", [])

    if not matches:
        await smart_send(interaction, content="🚫 Keine Matches vorhanden. Reminder-Test nicht möglich.", ephemeral=True)
        return

    # Zufälliges Match wählen
    match = random.choice(matches)

    team1 = match.get("team1", "Team 1")
    team2 = match.get("team2", "Team 2")
    match_id = match.get("match_id", "???")
    scheduled_time = match.get("scheduled_time", "Kein Termin")

    embed = create_embed_from_config("reminder_embed")
    embed.title = f"📢 Match-Reminder (Test)"
    embed.description = (
        f"**Match ID:** {match_id}\n"
        f"**Teams:** {team1} vs {team2}\n"
        f"**Geplanter Termin:** {scheduled_time}\n\n"
        f"Dies ist ein **Test-Reminder** für ein zufällig gewähltes Match."
    )

    await channel.send(embed=embed)
    await smart_send(interaction, content=f"✅ Reminder-Test mit Match-ID {match_id} erfolgreich gesendet.", ephemeral=True)

    logger.info(f"[TEST] Reminder-Embed für Match {match_id} ({team1} vs {team2}) erfolgreich im Channel #{channel.name} gesendet.")



