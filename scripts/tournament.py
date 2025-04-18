import asyncio
from datetime import datetime, timedelta
from typing import Optional

import discord
from discord import Interaction, Embed
from discord import app_commands

# Lokale Module
from .dataStorage import load_global_data
from .logger import setup_logger
from .matchmaker import auto_match_solo, create_round_robin_schedule, generate_schedule_overview
from .utils import has_permission, update_player_stats
from .dataStorage import load_tournament_data, save_tournament_data
from .poll import PollView
from .embeds import send_tournament_announcement, send_list_matches_embed, send_match_schedule_embed
from .stats import autocomplete_players, autocomplete_teams

# Setup Logger
logger = setup_logger("logs")



# ---------------------------------------
# 🎯 Start Turnier Command
# ---------------------------------------

@app_commands.command(name="start_tournament", description="Startet ein neues Turnier (Admin).")
@app_commands.describe(
    registration_hours="Wie viele Stunden soll die Anmeldung offen bleiben? (Standard: 48)",
    tournament_hours="Wie viele Stunden soll das Turnier laufen? (Standard: 168)"
)
async def start_tournament(interaction: Interaction, registration_hours: Optional[int] = 48, tournament_hours: Optional[int] = 168):
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
        return
    # Schutz: Läuft bereits ein Turnier?
    tournament = load_tournament_data()
    if tournament.get("running", False):
        await interaction.response.send_message("🚫 Es läuft bereits ein Turnier! Bitte beende es zuerst mit `/end_tournament`.", ephemeral=True)
        return

    now = datetime.now()
    registration_end = now + timedelta(hours=registration_hours)
    tournament_end = now + timedelta(hours=registration_hours + tournament_hours)

    # Turnierdaten vorbereiten
    tournament = {
        "registration_open": False,   # WICHTIG: Erst NACH der Umfrage öffnen
        "running": True,
        "teams": {},
        "solo": [],
        "registration_end": registration_end.isoformat(),
        "tournament_end": tournament_end.isoformat(),
        "matches": []
    }
    save_tournament_data(tournament)
    logger.info(f"[TOURNAMENT] Neues Turnier gestartet – Anmeldung bis {registration_end}.")

    # 2. Spiele-Abstimmung starten
    poll_options = load_global_data().get("games", [])
    view = PollView(options=poll_options, registration_period=registration_hours * 3600)
    await interaction.response.send_message("🎮 Bitte stimmt ab, welches Spiel gespielt werden soll:", view=view, ephemeral=False)
    logger.info("[TOURNAMENT] Umfrage gestartet.")

    # 3. Admin-Feedback
    await interaction.followup.send("✅ Turnier erfolgreich gestartet und Umfrage läuft.", ephemeral=True)

    # 4. Registrierung automatisch nach Ablauf schließen
    await asyncio.sleep(1)  # Mini-Wartezeit, damit sich Discord beruhigt
    asyncio.create_task(close_registration_after_delay(registration_hours * 3600, interaction.channel))

@app_commands.command(name="end_tournament", description="Beende das aktuelle Turnier manuell (Admin).")
async def end_tournament(interaction: Interaction):
    tournament = load_tournament_data()

    if not tournament.get("running", False):
        await interaction.response.send_message("❌ Es läuft derzeit kein aktives Turnier.", ephemeral=True)
        return

    tournament["running"] = False
    tournament["registration_open"] = False
    save_tournament_data(tournament)

    await interaction.response.send_message("🏁 Turnier wurde manuell beendet!", ephemeral=False)
    logger.info("[TOURNAMENT] Turnier manuell beendet über /end_tournament.")

@app_commands.command(name="list_matches", description="Zeigt alle geplanten Matches an.")
async def list_matches(interaction: Interaction):
    tournament = load_tournament_data()
    matches = tournament.get("matches", [])

    await send_list_matches_embed(interaction, matches)
    logger.info(f"[MATCHES] {len(matches)} Matches aufgelistet.")

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
    await asyncio.sleep(delay_seconds)
    tournament = load_tournament_data()
    tournament["registration_open"] = False
    save_tournament_data(tournament)

    # Jetzt Spieler paaren und Spielplan erstellen
    auto_match_solo()
    create_round_robin_schedule()

    await channel.send("🚫 **Die Anmeldephase ist jetzt geschlossen!**")
    logger.info("[TOURNAMENT] Anmeldung automatisch geschlossen.")

    # Starte automatisches Matchmaking
    new_teams = auto_match_solo()
    if new_teams:
        msg = "**🤝 Neue Teams aus der Solo-Anmeldung:**\n"
        for team, members in new_teams.items():
            msg += f"• **{team}**: {', '.join(members)}\n"
        await channel.send(msg)
    else:
        await channel.send("⚠️ Es konnten keine neuen Teams gebildet werden.")

async def close_tournament_after_delay(delay_seconds: int, channel: discord.TextChannel):
    await asyncio.sleep(delay_seconds)
    tournament = load_tournament_data()
    tournament["running"] = False
    save_tournament_data(tournament)

    await channel.send("🏁 **Das Turnier ist offiziell beendet! Glückwunsch an alle Teilnehmer!**")
    logger.info("[TOURNAMENT] Turnier automatisch beendet.")



