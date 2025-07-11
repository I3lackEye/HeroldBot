# modules/admin_tools.py

import os
import zipfile
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
import asyncio


import discord
from discord import Interaction, app_commands
from discord.ext import commands

# Lokale Module
from modules import poll
from modules.archive import archive_current_tournament
from modules.dataStorage import (
    load_global_data,
    load_tournament_data,
    add_game,
    remove_game,
    save_global_data,
    save_tournament_data,
    load_games
)
from modules.embeds import send_match_schedule, load_embed_template, build_embed_from_template
from modules.logger import logger
from modules.task_manager import add_task
from modules.matchmaker import (
    auto_match_solo,
    cleanup_orphan_teams,
    create_round_robin_schedule,
    generate_and_assign_slots,
    generate_schedule_overview,
)
from modules.modals import (
    AddGameModal,
    TestModal,
    StartTournamentModal
)

from modules.poll import end_poll
from modules.shared_states import pending_reschedules
from modules.tournament import end_tournament_procedure, auto_end_poll
from modules.utils import (
    autocomplete_teams,
    games_autocomplete,
    has_permission,
    smart_send,
)


# ----------------------------------------
# Admin-Helper functions
# ----------------------------------------
async def force_sign_out(interaction: Interaction, user_mention: str):
    tournament = load_tournament_data()
    updated = False
    user_mention = interaction.user.mention
    user_name = interaction.user.display_name

    for team, team_entry in tournament.get("teams", {}).items():
        if user_mention in team_entry.get("members", []):
            del tournament["teams"][team]
            logger.info(f"[ADMIN] {user_mention} wurde aus Team '{team}' entfernt." f"Team aufgelöst.")

            other_members = [m for m in team_entry.get("members", []) if m != user_mention]
            if other_members:
                verfugbarkeit = team_entry.get("verfügbarkeit", "")
                tournament.setdefault("solo", []).append({"player": other_members[0], "verfügbarkeit": verfugbarkeit})
                logger.info(
                    f"[ADMIN] {user_name} wurde in die Solo-Liste übernommen" f"mit Verfügbarkeit: {verfugbarkeit}"
                )
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
        await interaction.response.send_message(
            f"✅ {user_name} wurde erfolgreich aus dem Turnier entfernt.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            f"⚠ {user_name} ist weder in einem Team noch in der Solo-Liste registriert.",
            ephemeral=True,
        )


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
            choices.append(app_commands.Choice(name=f"Match {match_id}", value=match_id))

    return choices[:25]  # Maximal 25 Einträge zurückgeben

async def handle_start_tournament_modal(
    interaction: Interaction,
    poll_duration: int,
    registration_duration: int,
    tournament_weeks: int,
    team_size: int,
):
    logger.debug("[MODAL] handle_start_tournament_modal() wurde aufgerufen")

    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.followup.send("🚫 Keine Berechtigung.", ephemeral=True)
        return

    try:
        tournament = load_tournament_data()
        if tournament.get("running", False):
            await interaction.followup.send(
                "🚫 Es läuft bereits ein Turnier! Bitte beende es zuerst mit `/admin end_tournament`.",
                ephemeral=True,
            )
            return

        now = datetime.now(ZoneInfo("Europe/Berlin"))
        registration_end = now + timedelta(hours=registration_duration)
        tournament_end = registration_end + timedelta(weeks=max(tournament_weeks, 1))

        tournament = {
            "registration_open": False,
            "running": True,
            "teams": {},
            "solo": [],
            "registration_end": registration_end.astimezone(ZoneInfo("UTC")).isoformat(),
            "tournament_end": tournament_end.isoformat(),
            "matches": [],
            "team_size": team_size,
        }
        save_tournament_data(tournament)

        logger.info(
            f"[TOURNAMENT] Turnier gestartet: "
            f"Poll {poll_duration}h, Registrierung {registration_duration}h, Laufzeit {tournament_weeks} Woche(n), Teamgröße {team_size}"
        )

        # Embed senden
        template = load_embed_template("tournament_start", category="default").get("TOURNAMENT_ANNOUNCEMENT")
        embed = build_embed_from_template(template) if template else Embed(
            title="🎮 Turnier gestartet!",
            description=f"Die Spielumfrage läuft jetzt für {poll_duration} Stunden.",
            color=discord.Color.green(),
        )
        await interaction.followup.send(embed=embed, ephemeral=False)

        # Spiele laden
        poll_options = load_games()
        visible_games = {
            k: v for k, v in poll_options.items() if v.get("visible_in_poll", True)
        }
        if not visible_games:
            await interaction.followup.send("⚠️ Keine Spiele verfügbar für die Umfrage.", ephemeral=True)
            logger.warning("[MODAL] Keine Spiele mit visible_in_poll=True gefunden.")
            return

        logger.info(f"[MODAL] {len(visible_games)} Spiele geladen: {list(visible_games.keys())}")

        # Poll starten
        await poll.start_poll(
            interaction.channel,
            visible_games,
            registration_hours=registration_duration,
            poll_duration_hours=poll_duration,
        )

        # Timer setzen
        duration_seconds = poll_duration * 3600
        add_task(
            "auto_end_poll",
            asyncio.create_task(auto_end_poll(interaction.client, interaction.channel, duration_seconds)),
        )

    except Exception as e:
        logger.error(f"[MODAL] Fehler beim Start des Turniers: {e}")
        await interaction.followup.send(
            f"❌ Fehler beim Starten des Turniers: {e}", ephemeral=True
        )



# ----------------------------------------
# Slash Functions
# ----------------------------------------
class AdminGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="admin", description="Admin- und Mod-Befehle")

    # --------- ADMIN-BEFEHLE ----------
    @app_commands.command(
        name="sign_out",
        description="Admin-Befehl: Entfernt einen Spieler aus dem Turnier.",
    )
    @app_commands.describe(user="Der Spieler, der entfernt werden soll.")
    async def sign_out(self, interaction: Interaction, user: discord.Member):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
            return

        await force_sign_out(interaction, user.mention)

    @app_commands.command(
        name="add_win",
        description="Admin-Befehl: Vergibt manuell einen Turniersieg an einen Spieler.",
    )
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

        await interaction.response.send_message(
            f"✅ {user.mention} wurde ein zusätzlicher Sieg gutgeschrieben.",
            ephemeral=True,
        )
        logger.info(f"[ADMIN] {user.display_name} wurde manuell ein Sieg hinzugefügt.")


    @app_commands.command(
        name="start_tournament",
        description="Startet ein neues Turnier über ein Eingabeformular.",
    )
    async def start_tournament(self, interaction: Interaction):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 Keine Berechtigung.", ephemeral=True)
            return

        await interaction.response.send_modal(StartTournamentModal(interaction))


    @app_commands.command(name="end_tournament", description="Admin-Befehl: Beendet das aktuelle Turnier.")
    async def end_tournament(self, interaction: Interaction):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        await interaction.followup.send(
            "🏁 Turnierende wird vorbereitet... dies kann ein paar Sekunden dauern!",
            ephemeral=True,
        )

        await end_tournament_procedure(interaction.channel, manual_trigger=True)


    @app_commands.command(
        name="add_game",
        description="Admin-Befehl: Fügt ein neues Spiel zur Spielauswahl hinzu.",
    )
    async def add_game_command(self, interaction: Interaction):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
            return

        logger.debug("🧪 Slash-Command /admin add_game wurde ausgeführt")
        await interaction.response.send_modal(AddGameModal())


    @app_commands.command(name="remove_game", description="Entfernt ein Spiel aus der globalen Spielesammlung.")
    @app_commands.describe(game="Spiel-ID oder Name des Spiels")
    @app_commands.autocomplete(game=games_autocomplete)
    async def remove_game_command(self, interaction: Interaction, game: str):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 Keine Berechtigung.", ephemeral=True)
            return

        try:
            remove_game(game)
            await interaction.response.send_message(f"🗑 Spiel `{game}` wurde entfernt.", ephemeral=True)
        except ValueError as e:
            await interaction.response.send_message(f"⚠️ {str(e)}", ephemeral=True)


    @app_commands.command(
        name="award_overall_winner",
        description="Admin-Befehl: Trägt den Gesamtsieger des Turniers ein.",
    )
    @app_commands.describe(
        winning_team="Name des Gewinnerteams.",
        points="Erzielte Punkte.",
        game="Gespieltes Spiel.",
    )
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
            "ended_at": str(datetime.now()),
        }
        save_global_data(global_data)
        await interaction.response.send_message(
            f"✅ Gesamtsieger **{winning_team}** mit {points} Punkten in {game} eingetragen!",
            ephemeral=False,
        )
        logger.info(f"[ADMIN] Gesamtsieger {winning_team} eingetragen: {points} Punkte in {game}.")

    @app_commands.command(name="report_match", description="Trage das Ergebnis eines Matches ein.")
    @app_commands.describe(
        team="Dein Teamname",
        opponent="Gegnerischer Teamname",
        result="Ergebnis auswählen",
    )
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
            await interaction.response.send_message(
                "🚫 Du kannst nicht gegen dein eigenes Team spielen!", ephemeral=True
            )
            return

        if result.lower() not in ["win", "loss"]:
            await interaction.response.send_message(
                "🚫 Ungültiges Ergebnis. Bitte gib **win** oder **loss** an.",
                ephemeral=True,
            )
            return

        # Match speichern
        match_entry = {
            "team": team,
            "opponent": opponent,
            "result": result.lower(),
            "timestamp": datetime.now().isoformat(),
        }
        matches.append(match_entry)
        tournament["matches"] = matches
        save_tournament_data(tournament)

        await interaction.response.send_message(
            f"✅ Ergebnis gespeichert:\n\n**{team}** vs **{opponent}**\n➔ Ergebnis: **{result.upper()}**",
            ephemeral=True,
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

    @app_commands.command(
        name="close_registration",
        description="(Admin) Schließt die Anmeldung und startet die Matchgenerierung.",
    )
    async def close_registration(self, interaction: Interaction):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung.", ephemeral=True)
            return

        tournament = load_tournament_data()

        if not tournament.get("running", False) or not tournament.get("registration_open", False):
            await interaction.response.send_message(
                "⚠️ Die Anmeldung ist bereits geschlossen oder es läuft kein Turnier.",
                ephemeral=True,
            )
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

    @app_commands.command(name="archive_tournament", description="Archiviert das aktuelle Turnier.")
    async def archive_tournament(self, interaction: Interaction):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
            return

        file_path = archive_current_tournament()
        await interaction.response.send_message(f"✅ Turnier archiviert: `{file_path}`", ephemeral=True)

        logger.info(f"[ARCHIVE] Turnier erfolgreich archiviert unter {file_path}")

    @app_commands.command(
        name="reset_reschedule",
        description="Setzt eine offene Reschedule-Anfrage manuell zurück.",
    )
    @app_commands.describe(match_id="Match-ID auswählen")
    @app_commands.autocomplete(match_id=pending_match_autocomplete)
    async def reset_reschedule(self, interaction: Interaction, match_id: int):
        global pending_reschedules
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
            return

        if match_id in pending_reschedules:
            pending_reschedules.discard(match_id)
            await interaction.response.send_message(
                f"✅ Reschedule-Anfrage für Match {match_id} wurde zurückgesetzt.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"⚠️ Keine offene Anfrage für Match {match_id} gefunden.", ephemeral=True
            )

    @app_commands.command(
        name="end_poll",
        description="Beendet die aktuelle Spielumfrage und startet die Anmeldung.",
    )
    async def end_poll_command(self, interaction: discord.Interaction):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung dafür.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            await end_poll(interaction.client, interaction.channel)
            logger.info("[END_POLL] end_poll() erfolgreich abgeschlossen.")
            await interaction.edit_original_response(content="✅ Umfrage wurde beendet!")
        except Exception as e:
            logger.error(f"[END_POLL] Fehler beim Beenden der Umfrage: {e}")
            await interaction.edit_original_response(content=f"❌ Fehler beim Beenden der Umfrage: {e}")

    @app_commands.command(
        name="export_data",
        description="Exportiert alle aktuellen Turnierdaten als ZIP-Datei (per DM).",
    )
    async def export_data(self, interaction: Interaction):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 Keine Berechtigung.", ephemeral=True)
            return

        export_dir = "exports"
        os.makedirs(export_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_name = f"tournament_export_{timestamp}.zip"
        zip_path = os.path.join(export_dir, zip_name)

        with zipfile.ZipFile(zip_path, "w") as zipf:
            for f in ["data/data.json", "data/tournament.json"]:
                if os.path.exists(f):
                    zipf.write(f)

        file = discord.File(zip_path)

        # ✅ Versuch, per DM zu senden
        try:
            await interaction.user.send(content="📦 Hier ist dein Turnier-Export:", file=file)
            await interaction.response.send_message("✅ ZIP-Datei wurde dir per DM geschickt.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "⚠️ Konnte dir keine DM schicken. Stelle sicher, dass DMs vom Server erlaubt sind.",
                ephemeral=True,
            )


# ----------------------------------------
# Hook for Cog
# ----------------------------------------
class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.tree.add_command(AdminGroup())


# Extension setup:
async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
