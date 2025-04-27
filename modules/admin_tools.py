import discord
from discord import app_commands, Interaction
from discord.ext import commands
from typing import Optional
from datetime import datetime
import random
from random import randint, choice


# Lokale Module
from .dataStorage import load_global_data, save_global_data, load_tournament_data, save_tournament_data, load_config, add_game, remove_game
from .utils import has_permission, generate_team_name, smart_send, generate_random_availability, parse_availability, game_autocomplete, autocomplete_teams, autocomplete_players
from .logger import logger
from .stats import autocomplete_players
from .matchmaker import auto_match_solo, create_round_robin_schedule, generate_and_assign_slots, generate_schedule_overview, cleanup_orphan_teams, generate_weekend_slots
from .embeds import send_match_schedule, load_embed_template, build_embed_from_template
from modules.archive import archive_current_tournament
from modules.shared_states import pending_reschedules



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

async def pending_match_autocomplete(interaction: Interaction, current: str):
    """
    Autocomplete für offene Reschedule-Matches (nur IDs).
    """
    choices = []
    
    # Falls keine offenen Reschedules existieren ➔ nichts vorschlagen
    if not pending_reschedules:
        return []

    for match_id in pending_reschedules:
        if current in str(match_id):  # Filtert nach eingegebener Zahl
            choices.append(
                app_commands.Choice(
                    name=f"Match {match_id}",
                    value=match_id
                )
            )

    return choices[:25]  # Maximal 25 Einträge zurückgeben

# ----------------------------------------
# Admin Slash-Commands
# ----------------------------------------
class AdminGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="admin", description="Liste an Admin/Debug Befehlen")

    @app_commands.command(name="abmelden", description="Admin-Befehl: Entfernt einen Spieler aus dem Turnier.")
    @app_commands.describe(user="Der Spieler, der entfernt werden soll.")
    async def abmelden(self, interaction: Interaction, user: discord.Member):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
            return

        await force_sign_out(interaction, user.mention)

    @app_commands.command(name="add_win", description="Admin-Befehl: Vergibt manuell einen Turniersieg an einen Spieler.")
    @app_commands.describe(user="Der Spieler, der den Sieg erhalten soll.")
    async def add_win(self, interaction: Interaction, user: discord.Member):
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

    @app_commands.command(name="end_tournament", description="Admin-Befehl: Beendet das aktuelle Turnier.")
    async def end_tournament(self, interaction: Interaction):
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
    async def add_game_command(self, interaction: Interaction, game: str):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
            return

        try:
            add_game(game)  # --> nutzt deine Backend-Logik!
            await interaction.response.send_message(f"✅ Das Spiel **{game}** wurde erfolgreich hinzugefügt.", ephemeral=True)
        except ValueError as e:
            await interaction.response.send_message(f"⚠️ {str(e)}", ephemeral=True)

    @app_commands.command(name="remove_game", description="Admin-Befehl: Entfernt ein Spiel aus der Spielauswahl.")
    @app_commands.describe(game="Name des Spiels, das entfernt werden soll.")
    @app_commands.autocomplete(game=game_autocomplete)
    async def remove_game_command(self, interaction: Interaction, game: str):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
            return

        try:
            remove_game(game)
            await interaction.response.send_message(f"✅ Das Spiel **{game}** wurde erfolgreich entfernt.", ephemeral=True)
        except ValueError as e:
            await interaction.response.send_message(f"⚠️ {str(e)}", ephemeral=True)

    @app_commands.command(name="award_overall_winner", description="Admin-Befehl: Trägt den Gesamtsieger des Turniers ein.")
    @app_commands.describe(winning_team="Name des Gewinnerteams.", points="Erzielte Punkte.", game="Gespieltes Spiel.")
    @app_commands.autocomplete(winning_team=autocomplete_teams)
    async def award_overall_winner(self, interaction: Interaction, winning_team: str, points: int, game: str):
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
    async def report_match(self, interaction: Interaction, team: str, opponent: str, result: str):
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
    async def reload_commands(self, interaction: Interaction):
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
    async def close_registration(self, interaction: Interaction):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung.", ephemeral=True)
            return

        tournament = load_tournament_data()

        if not tournament.get("running", False) or not tournament.get("registration_open", False):
            await interaction.response.send_message("⚠️ Die Anmeldung ist bereits geschlossen oder es läuft kein Turnier.", ephemeral=True)
            return

        # Anmeldung schließen
        tournament["registration_open"] = False
        save_tournament_data(tournament)

        await smart_send(interaction, content="🚫 **Die Anmeldung wurde geschlossen.**")
        logger.info("[TOURNAMENT] Anmeldung manuell geschlossen.")

        # Verwaiste Teams aufräumen
        await cleanup_orphan_teams(interaction.channel)

        # Solo-Spieler automatisch matchen
        auto_match_solo()

        # Matchplan erstellen
        create_round_robin_schedule()

        # Alle übrig gebliebenen Solo-Spieler entfernen
        tournament = load_tournament_data()
        tournament["solo"] = []
        save_tournament_data(tournament)

        # Matches laden
        tournament = load_tournament_data()
        matches = tournament.get("matches", [])

        # Slots generieren und Matches verteilen
        await generate_and_assign_slots()

        # Nach dem Verteilen neu laden
        tournament = load_tournament_data()
        matches = tournament.get("matches", [])

        # Überblick posten
        description_text = generate_schedule_overview(matches)
        await send_match_schedule(interaction, description_text)

    @app_commands.command(name="generate_dummy", description="(Admin) Erzeugt Dummy-Solos und Dummy-Teams zum Testen.")
    @app_commands.describe(num_solo="Anzahl Solo-Spieler", num_teams="Anzahl Teams")
    async def generate_dummy_teams(self, interaction: Interaction, num_solo: int = 4, num_teams: int = 2):
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

    @app_commands.command(name="test_reminder", description="Testet ein Reminder-Embed mit einem zufälligen Match.")
    async def test_reminder(self, interaction: Interaction):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
            return
        
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
        teams = tournament.get("teams", {})

        if not matches:
            await smart_send(interaction, content="🚫 Keine Matches vorhanden. Reminder-Test nicht möglich.", ephemeral=True)
            return

        # Zufälliges Match wählen
        match = random.choice(matches)

        # Team-Mitglieder sammeln (bereits im Mention-Format gespeichert)
        team1_members = teams.get(match.get("team1", ""), {}).get("members", [])
        team2_members = teams.get(match.get("team2", ""), {}).get("members", [])
        all_mentions = " ".join(team1_members + team2_members)

        # Platzhalter setzen
        placeholders = {
            "match_id": match.get("match_id", "???"),
            "team1": match.get("team1", "Team 1"),
            "team2": match.get("team2", "Team 2"),
            "time": match.get("scheduled_time", "Kein Termin").replace("T", " ")[:16],
            "mentions": all_mentions
        }

        # Template laden
        template = load_embed_template("reminder", category="default").get("REMINDER")
        if not template:
            logger.error("[EMBED] REMINDER Template fehlt.")
            await smart_send(interaction, content="🚫 Reminder-Template fehlt.", ephemeral=True)
            return

        # Embed bauen und senden
        embed = build_embed_from_template(template, placeholders)
        await channel.send(embed=embed)
        await smart_send(interaction, content=f"✅ Reminder-Test mit Match-ID {placeholders['match_id']} erfolgreich gesendet.", ephemeral=True)

        logger.info(f"[TEST] Reminder-Embed für Match {placeholders['match_id']} ({placeholders['team1']} vs {placeholders['team2']}) im Channel #{channel.name} gesendet.")

    @app_commands.command(name="archive_tournament", description="Archiviert das aktuelle Turnier.")
    async def archive_tournament(self, interaction: Interaction):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
            return

        file_path = archive_current_tournament()
        await interaction.response.send_message(f"✅ Turnier archiviert: `{file_path}`", ephemeral=True)

        logger.info(f"[ARCHIVE] Turnier erfolgreich archiviert unter {file_path}")

    @app_commands.command(name="reset_reschedule", description="Setzt eine offene Reschedule-Anfrage manuell zurück.")
    @app_commands.describe(match_id="Match-ID auswählen")
    @app_commands.autocomplete(match_id=pending_match_autocomplete) 
    async def reset_reschedule(self, interaction: Interaction, match_id: int):
        global pending_reschedules
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
            return

        if match_id in pending_reschedules:
            pending_reschedules.discard(match_id)
            await interaction.response.send_message(f"✅ Reschedule-Anfrage für Match {match_id} wurde zurückgesetzt.", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ Keine offene Anfrage für Match {match_id} gefunden.", ephemeral=True)
# Registrierung im Bot
async def setup(bot: commands.Bot):
    bot.tree.add_command(AdminGroup())