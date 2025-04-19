import asyncio
from datetime import datetime, timedelta
from typing import Optional

import discord
from discord import Interaction, Embed
from discord import app_commands

# Lokale Module
from .dataStorage import load_global_data
from .logger import logger
from .matchmaker import auto_match_solo, create_round_robin_schedule, generate_schedule_overview, assign_matches_to_slots, cleanup_orphan_teams
from .utils import has_permission, update_player_stats, get_player_team, autocomplete_teams
from .dataStorage import load_tournament_data, save_tournament_data, backup_current_state, reset_tournament, delete_tournament_file
from .poll import PollView
from .embeds import send_tournament_announcement, send_list_matches, send_match_schedule, load_embed_template, build_embed_from_template, send_tournament_end_announcement  
from .stats import autocomplete_players, autocomplete_teams, get_mvp
from modules.archive import archive_current_tournament

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
    poll_options = load_global_data().get("games", [])
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

    # 1. Archivieren
    archive_path = archive_current_tournament()
    logger.info(f"[END] Turnier archiviert unter: {archive_path}")

    # 2. MVP bestimmen
    mvp = get_mvp()  # kleine Hilfsfunktion basierend auf player_stats
    mvp_message = f"🏆 MVP des Turniers: **{mvp}**!" if mvp else "🏆 Kein MVP ermittelt."

    # 3. Backup vor Reset erstellen
    backup_current_state()

    # 4. Cleanup durchführen
    reset_tournament()

    # 5. Turnierdatei löschen
    delete_tournament_file()

    # 6. Abschluss-Embed senden
    await send_tournament_end_announcement(interaction.channel, mvp_message)

    await interaction.response.send_message("✅ Turnier erfolgreich beendet, archiviert und aufgeräumt.", ephemeral=True)

    logger.info("[END] Turnier abgeschlossen, System bereit für neue Turniere.")


@app_commands.command(name="list_matches", description="Zeigt alle geplanten Matches oder die eines bestimmten Teams.")
@app_commands.describe(team="Optional: Name des Teams oder 'meine' für eigene Matches.")
@app_commands.autocomplete(team=autocomplete_teams)
async def list_matches(interaction: Interaction, team: Optional[str] = None):
    tournament = load_tournament_data()
    matches = tournament.get("matches", [])

    if team:
        # Nur bestimmte Matches
        user_id = str(interaction.user.id)
        if team.lower() == "meine":
            # Eigene Matches basierend auf User-ID finden
            my_team = get_player_team(tournament, user_id)
            if not my_team:
                await smart_send(interaction, content="🚫 Du bist in keinem Team registriert.", ephemeral=True)
                return
            matches = [m for m in matches if m.get("team1") == my_team or m.get("team2") == my_team]
        else:
            # Bestimmtes Team gesucht
            matches = [m for m in matches if m.get("team1") == team or m.get("team2") == team]

    if not matches:
        await smart_send(interaction, content="⚠️ Keine passenden Matches gefunden.", ephemeral=True)
        return

    await send_list_matches(interaction, matches)
    logger.info(f"[MATCHES] {len(matches)} Matches aufgelistet (Filter: {team or 'alle'}).")

@app_commands.command(name="match_schedule", description="Zeigt den aktuellen Spielplan an.")
async def match_schedule(interaction: Interaction):
    tournament = load_tournament_data()
    matches = tournament.get("matches", [])

    if not matches:
        await interaction.response.send_message("⚠️ Kein Spielplan vorhanden.", ephemeral=True)
        return

    lines = []
    for match in sorted(matches, key=lambda m: m["scheduled_time"] or ""):
        time = match.get("scheduled_time", "Noch nicht geplant")
        team1 = match.get("team1")
        team2 = match.get("team2")
        status = match.get("status", "offen")
        emoji = "✅" if status == "erledigt" else "🕒"
        lines.append(f"{emoji} {time} – **{team1}** vs **{team2}**")

    description = "\n".join(lines) if lines else "Keine Matches geplant."

    # ➔ Jetzt schickst du das Embed los!
    description_text = generate_schedule_overview()
    await send_match_schedule_embed(interaction, description_text)

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
    assign_matches_to_slots()

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
    tournament = load_tournament_data()
    tournament["running"] = False
    save_tournament_data(tournament)

    await channel.send("🏁 **Das Turnier ist offiziell beendet! Glückwunsch an alle Teilnehmer!**")
    logger.info("[TOURNAMENT] Turnier automatisch beendet.")



