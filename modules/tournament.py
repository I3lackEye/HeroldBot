import asyncio
from datetime import datetime, timedelta
from typing import Optional

import discord
from discord import Interaction, Embed
from discord import app_commands

# Lokale Module
from .dataStorage import load_global_data, load_games
from .logger import logger
from .matchmaker import auto_match_solo, create_round_robin_schedule, generate_schedule_overview, assign_matches_to_slots, cleanup_orphan_teams
from .utils import has_permission, update_player_stats, get_player_team, autocomplete_teams, get_current_chosen_game, smart_send, update_all_participants
from .dataStorage import load_tournament_data, save_tournament_data, backup_current_state, reset_tournament, delete_tournament_file
from .poll import PollView
from .embeds import send_tournament_announcement, send_list_matches, load_embed_template, build_embed_from_template, send_tournament_end_announcement  
from .stats import autocomplete_players, autocomplete_teams, get_mvp, update_player_stats, get_winner_ids, get_winner_team
from modules.archive import archive_current_tournament, update_tournament_history

# ---------------------------------------
# 🎯 Start Turnier Command
# ---------------------------------------

@app_commands.command(name="start_tournament", description="Startet ein neues Turnier (Admin).")
@app_commands.describe(registration_hours="Wie viele Stunden soll die Anmeldung offen bleiben? (Standard: 72)", tournament_weeks="Wie viele Wochen soll das Turnier laufen? (Standard: 1)")
async def start_tournament(interaction: Interaction, registration_hours: Optional[int] = 72, tournament_weeks: Optional[int] = 1):
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
        return

    # Schutz: Läuft schon ein Turnier?
    tournament = load_tournament_data()
    if tournament.get("running", False):
        await interaction.response.send_message("🚫 Es läuft bereits ein Turnier! Bitte beende es erst mit `/end_tournament`.", ephemeral=True)
        return

    now = datetime.now()

    # Berechnungen
    registration_end = now + timedelta(hours=registration_hours)
    tournament_end = registration_end + timedelta(weeks=tournament_weeks)

    # Schutz: Mindestens 1 Woche Turnierdauer
    if tournament_weeks < 1:
        tournament_end = registration_end + timedelta(weeks=1)
        logger.warning(f"[TOURNAMENT] Turnierdauer zu kurz angegeben. Automatisch auf 1 Woche gesetzt.")

    # Turnierdaten vorbereiten
    tournament = {
        "registration_open": False,  # Erst nach Poll öffnen!
        "running": True,
        "teams": {},
        "solo": [],
        "registration_end": registration_end.isoformat(),
        "tournament_end": tournament_end.isoformat(),
        "matches": []
    }
    save_tournament_data(tournament)

    logger.info(f"[TOURNAMENT] Neues Turnier gestartet – Anmeldung bis {registration_end}. Turnier läuft bis {tournament_end}.")

    # Lade Turnier-Start Embed
    template = load_embed_template("tournament_start", category="default").get("TOURNAMENT_ANNOUNCEMENT")
    embed = build_embed_from_template(template)

    # 1. Direkt als Antwort auf den Slash-Command: Turnierstart-Embed
    await interaction.response.send_message(embed=embed)

    # Umfrage starten
    poll_options = load_games()
    view = PollView(options=poll_options, registration_period=registration_hours * 3600)
    await interaction.followup.send(content="🎮 Bitte stimmt ab, welches Spiel gespielt werden soll:", view=view)

    logger.info("[TOURNAMENT] Turnier gestartet und Umfrage läuft.")

    # Admin-Info
    #await interaction.followup.send("✅ Turnier erfolgreich gestartet. Umfrage läuft!", ephemeral=True)

    # Timer für automatische Schließung der Anmeldung
    asyncio.create_task(close_registration_after_delay(registration_hours * 3600, interaction.channel))

@app_commands.command(name="end_tournament", description="Beendet das aktuelle Turnier, archiviert es und räumt auf.")
async def end_tournament(interaction: Interaction):
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
        return

    await end_tournament_procedure(interaction.channel, manual_trigger=True)
    await interaction.response.send_message("✅ Turnier wurde manuell beendet und archiviert.", ephemeral=True)

@app_commands.command(name="list_matches", description="Zeigt alle geplanten Matches oder die eines bestimmten Teams.")
@app_commands.describe(team="Optional: Name des Teams oder 'meine' für eigene Matches.")
@app_commands.autocomplete(team=autocomplete_teams)
async def list_matches(interaction: Interaction, team: Optional[str] = None):
    tournament = load_tournament_data()
    matches = tournament.get("matches", [])

    user_id = str(interaction.user.id)

    if team:
        team = team.lower()

        if team == "meine":
            # Eigene Teamzugehörigkeit herausfinden
            my_team = get_player_team(tournament, user_id)
            if not my_team:
                await smart_send(interaction, content="🚫 Du bist in keinem Team registriert.", ephemeral=True)
                return

            matches = [m for m in matches if m.get("team1", "").lower() == my_team.lower() or m.get("team2", "").lower() == my_team.lower()]
        else:
            # Nach spezifischem Team suchen
            matches = [m for m in matches if m.get("team1", "").lower() == team or m.get("team2", "").lower() == team]

    if not matches:
        await smart_send(interaction, content="⚠️ Keine passenden Matches gefunden.", ephemeral=True)
        return

    await send_list_matches(interaction, matches)

    logger.info(f"[MATCHES] {len(matches)} Matches aufgelistet (Filter: '{team or 'alle'}').")

# ---------------------------------------
# Hilfsfunktion
# ---------------------------------------

async def end_tournament_procedure(channel: discord.TextChannel, manual_trigger: bool = False):
    tournament = load_tournament_data()

    if not manual_trigger and not all_matches_completed():
        logger.info("[TOURNAMENT] Nicht alle Matches abgeschlossen. Abbruch des automatischen Endes.")
        await channel.send("⚠️ Es sind noch nicht alle Matches abgeschlossen. Turnier bleibt offen.")
        return

    # Archivieren
    archive_path = archive_current_tournament()
    logger.info(f"[END] Turnier archiviert unter: {archive_path}")

    # Backup
    backup_current_state()

    # Gewinner und Spiel holen
    winner_ids = get_winner_ids()
    chosen_game = get_current_chosen_game()
    mvp = get_mvp()

    # 🆕 Teilnehmerstatistiken aktualisieren
    await update_all_participants()

    # Gewinner in Statistik eintragen
    if winner_ids and chosen_game != "Unbekannt":
        update_player_stats(winner_ids, chosen_game)
        logger.info(f"[END] Gewinner gespeichert: {winner_ids} für Spiel: {chosen_game}")
    else:
        logger.warning("[END] Keine Gewinner oder kein Spielname gefunden – Statistik nicht aktualisiert.")

    # Tournament-History aktualisieren
    update_tournament_history(
        winner_ids=winner_ids,
        chosen_game=chosen_game or "Unbekannt",
        mvp_name=mvp or "Kein MVP"
    )

    # System aufräumen
    reset_tournament()
    delete_tournament_file()

    # Abschlussmeldung als Embed
    mvp_message = f"🏆 MVP des Turniers: **{mvp}**!" if mvp else "🏆 Kein MVP ermittelt."
    await send_tournament_end_announcement(channel, mvp_message, winner_ids)

    logger.info("[END] Turnier abgeschlossen, System bereit für neue Turniere.")


# ---------------------------------------
# ⏳ Hintergrundaufgaben
# ---------------------------------------

async def close_registration_after_delay(delay_seconds: int, channel: discord.TextChannel):
    """
    Schließt die Anmeldung nach einer Verzögerung automatisch
    und startet das automatische Matchmaking & Cleanup.
    """
    await asyncio.sleep(delay_seconds)

    tournament = load_tournament_data()
    tournament["registration_open"] = False
    save_tournament_data(tournament)

    logger.info("[TOURNAMENT] Anmeldung automatisch geschlossen.")
    await channel.send("🚫 **Die Anmeldephase ist jetzt geschlossen!**")

    # Starte automatisches Matchmaking
    new_teams = auto_match_solo()
    create_round_robin_schedule()

    # ➡️ Matches und Slots neu laden und zuweisen
    matches = load_tournament_data().get("matches", [])
    slots = generate_weekend_slots(load_tournament_data())
    assign_matches_to_slots(matches, slots)

    save_tournament_data(load_tournament_data())

    # Ausgabe neu gebildeter Teams
    if new_teams:
        msg = "**🤝 Neue Teams aus der Solo-Anmeldung:**\n"
        for team, members in new_teams.items():
            msg += f"• **{team}**: {', '.join(members)}\n"
        await channel.send(msg)
    else:
        await channel.send("⚠️ Es konnten keine neuen Teams gebildet werden.")

    # Aufräumen von unvollständigen Teams
    await cleanup_orphan_teams(channel)

    logger.info("[TOURNAMENT] Cleanup abgeschlossen.")

async def close_tournament_after_delay(delay_seconds: int, channel: discord.TextChannel):
    await asyncio.sleep(delay_seconds)

    await end_tournament_procedure(channel)




