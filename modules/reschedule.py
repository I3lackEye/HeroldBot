# modules/reschedule.py

import asyncio
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import ButtonStyle, Embed, Interaction, app_commands
from discord.ext import commands
from discord.ui import Button, View

# Lokale modules
from modules.dataStorage import load_config, load_tournament_data, save_tournament_data
from modules.embeds import (
    build_embed_from_template,
    send_notify_team_members,
    send_request_reschedule,
)
from modules.logger import logger
from modules.matchmaker import generate_slot_matrix, get_valid_slots_for_match
from modules.shared_states import pending_reschedules
from modules.utils import get_player_team, get_team_open_matches, smart_send
from views.reschedule_view import RescheduleView

config = load_config()
RESCHEDULE_CHANNEL_ID = int(config.get("CHANNELS", {}).get("RESCHEDULE_CHANNEL_ID", 0))
RESCHEDULE_TIMEOUT_HOURS = int(config.get("RESCHEDULE_TIMEOUT_HOURS", 24))

# ---------------------------------------
# Helper: IDs extrahieren
# ---------------------------------------
def extract_ids(members):
    ids = []
    for m in members:
        match = re.search(r"\d+", m)
        if match:
            ids.append(match.group(0))
    return ids


def get_free_slots_for_match(tournament, match_id: int) -> list[datetime]:
    """
    Gibt alle erlaubten und freien Slots für ein bestimmtes Match zurück.
    """
    match = next((m for m in tournament.get("matches", []) if m["match_id"] == match_id), None)
    if not match:
        return []

    team1 = match["team1"]
    team2 = match["team2"]
    slot_matrix = generate_slot_matrix(tournament)

    all_valid = get_valid_slots_for_match(team1, team2, slot_matrix)

    # Entferne bereits belegte Slots
    booked = {m["scheduled_time"] for m in tournament["matches"] if m.get("scheduled_time")}
    return [slot for slot in all_valid if slot.isoformat() not in booked]


# ---------------------------------------
# Command: /request_reschedule
# ---------------------------------------
async def handle_request_reschedule(interaction: Interaction, match_id: int, neuer_zeitpunkt: str):
    global pending_reschedules
    tournament = load_tournament_data()
    user_id = str(interaction.user.id)

    # 1️⃣ Team und Match prüfen
    team_name = get_player_team(user_id)
    if not team_name:
        await interaction.response.send_message("🚫 Du bist in keinem Team registriert.", ephemeral=True)
        return

    open_matches = get_team_open_matches(team_name)
    open_match_ids = [m["match_id"] for m in open_matches]

    if match_id not in open_match_ids:
        await interaction.response.send_message("🚫 Ungültige Match-ID oder nicht dein Match!", ephemeral=True)
        return

    if match_id in pending_reschedules:
        await interaction.response.send_message(
            "🚫 Für dieses Match läuft bereits eine Reschedule-Anfrage!", ephemeral=True
        )
        return

    match = next(
        (m for m in tournament.get("matches", []) if m.get("match_id") == match_id),
        None,
    )
    if not match:
        await interaction.response.send_message("🚫 Match nicht gefunden.", ephemeral=True)
        return

    # 2️⃣ Neuer Zeitpunkt prüfen
    try:
        new_dt = datetime.strptime(neuer_zeitpunkt, "%d.%m.%Y %H:%M").replace(tzinfo=ZoneInfo("Europe/Berlin"))
    except ValueError:
        await interaction.response.send_message(
            "🚫 Ungültiges Datumsformat! Bitte benutze `TT.MM.JJJJ HH:MM`.",
            ephemeral=True,
        )
        return

    if new_dt <= datetime.now(ZoneInfo("Europe/Berlin")):
        await interaction.response.send_message("🚫 Der neue Zeitpunkt muss in der Zukunft liegen!", ephemeral=True)
        return

    # ✅ Slots prüfen – neue Matrix-basierte Logik
    allowed_slots = get_free_slots_for_match(tournament, match_id)
    allowed_iso = {slot.isoformat() for slot in allowed_slots}

    booked_slots = {m["scheduled_time"] for m in tournament["matches"] if m.get("scheduled_time")}
    free_slots = [slot for slot in allowed_iso if slot not in booked_slots]

    future_slots = [
        datetime.fromisoformat(slot).astimezone(ZoneInfo("Europe/Berlin"))
        for slot in free_slots
        if datetime.fromisoformat(slot).astimezone(ZoneInfo("Europe/Berlin")) > datetime.now(ZoneInfo("Europe/Berlin"))
    ]

    if new_dt not in future_slots:
        await interaction.response.send_message("🚫 Der gewählte Zeitpunkt ist kein erlaubter Slot!", ephemeral=True)
        return

    # 3️⃣ Match darf nicht zu knapp vor Start liegen
    scheduled_time_str = match.get("scheduled_time")
    if scheduled_time_str:
        scheduled_dt = datetime.fromisoformat(scheduled_time_str)
        if scheduled_dt - datetime.utcnow() <= timedelta(hours=1):
            await interaction.response.send_message(
                "🚫 Du kannst Matches nur bis spätestens 1 Stunde vor geplantem Beginn verschieben.",
                ephemeral=True,
            )
            return

    # 4️⃣ Anfrage starten
    pending_reschedules.add(match_id)
    interaction.client.loop.create_task(start_reschedule_timer(interaction.client, match_id))

    await interaction.response.defer(ephemeral=True)

    reschedule_channel = interaction.guild.get_channel(RESCHEDULE_CHANNEL_ID)
    if not reschedule_channel:
        await interaction.followup.send("🚫 Reschedule-Channel nicht gefunden.", ephemeral=True)
        return

    if not reschedule_channel.permissions_for(interaction.guild.me).send_messages:
        await interaction.followup.send("🚫 Keine Berechtigung im Reschedule-Channel.", ephemeral=True)
        return

    # 5️⃣ Teilnehmer vorbereiten
    team1 = match["team1"]
    team2 = match["team2"]
    members_team1 = tournament.get("teams", {}).get(team1, {}).get("members", [])
    members_team2 = tournament.get("teams", {}).get(team2, {}).get("members", [])
    all_mentions = members_team1 + members_team2

    valid_members = []
    for mention in all_mentions:
        if mention.startswith("<@"):
            try:
                uid = int(mention.replace("<@", "").replace("!", "").replace(">", ""))
                member = interaction.guild.get_member(uid)
                if member:
                    valid_members.append(member)
            except ValueError:
                continue

    if not valid_members:
        await interaction.followup.send(
            "🚫 Konnte keine gültigen Spieler für die Reschedule-Anfrage finden.",
            ephemeral=True,
        )
        return

    # 6️⃣ Anfrage-Embed und View senden
    await send_request_reschedule(reschedule_channel, match_id, team1, team2, new_dt, valid_members)

    # 7️⃣ Abschlussnachricht
    await interaction.followup.send("✅ Deine Reschedule-Anfrage wurde im Channel erstellt!", ephemeral=True)

    logger.info(f"[RESCHEDULE] Anfrage von {team_name} für Match {match_id} gestartet.")



# ---------------------------------------
# Autocomplete für Match-ID
# ---------------------------------------
async def match_id_autocomplete(interaction: Interaction, current: str):
    tournament = load_tournament_data()
    user_id = str(interaction.user.id)
    team_name = get_player_team(user_id)

    if not team_name:
        return []

    open_matches = get_team_open_matches(team_name)

    choices = []
    for m in open_matches:
        if current in str(m["match_id"]):
            choices.append(
                app_commands.Choice(
                    name=f"Match {m['match_id']}: {m['team1']} vs {m['team2']}",
                    value=m["match_id"],
                )
            )
    return choices[:25]  # Discord erlaubt maximal 25 Vorschläge


# ---------------------------------------
# Helper: Autocomplete für neue Terminwahl
# ---------------------------------------
async def neuer_zeitpunkt_autocomplete(interaction: Interaction, current: str):
    tournament = load_tournament_data()

    try:
        allowed_slots = get_free_slots_for_match(tournament, match_id)
        allowed_iso = {slot.isoformat() for slot in allowed_slots}

    except ValueError:
        return []

    # Schon belegte Slots heraussuchen
    booked_slots = set()
    for match in tournament.get("matches", []):
        if match.get("scheduled_time"):
            booked_slots.add(match["scheduled_time"])

    # Nur erlaubte & freie Slots
    free_slots = [slot for slot in allowed_iso if slot not in booked_slots]

    # Nur zukünftige Slots
    free_slots = [slot for slot in free_slots if datetime.fromisoformat(slot) > datetime.now()]

    if current:
        free_slots = [slot for slot in free_slots if current in slot]

    choices = []
    for slot in free_slots[:25]:
        dt = datetime.fromisoformat(slot)
        label = f"{dt.strftime('%A')} {dt.strftime('%d.%m.%Y %H:%M')} Uhr"
        value = dt.strftime("%d.%m.%Y %H:%M")
        choices.append(app_commands.Choice(name=label, value=value))

    return choices


async def start_reschedule_timer(bot, match_id: int):
    """
    Wartet eine bestimmte Zeit und entfernt dann die Reschedule-Anfrage automatisch.
    Benachrichtigt optional den Reschedule-Channel.
    """
    await asyncio.sleep(RESCHEDULE_TIMEOUT_HOURS * 3600)  # Timeout warten

    if match_id in pending_reschedules:
        pending_reschedules.discard(match_id)
        logger.info(
            f"[RESCHEDULE] Automatische Aufräumung: Match {match_id} wurde zurückgesetzt (Timeout nach {RESCHEDULE_TIMEOUT_HOURS} Stunden)."
        )

        # ➔ Nachricht im Reschedule-Channel schicken
        reschedule_channel = bot.get_channel(RESCHEDULE_CHANNEL_ID)
        if reschedule_channel:
            await reschedule_channel.send(
                f"❗ Die Reschedule-Anfrage für Match `{match_id}` wurde automatisch beendet, da keine Einigung innerhalb von {RESCHEDULE_TIMEOUT_HOURS} Stunden erzielt wurde."
            )
