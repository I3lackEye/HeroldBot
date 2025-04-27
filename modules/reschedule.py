from discord import app_commands, Interaction, ButtonStyle, Embed
from discord.ext import commands
from discord.ui import View, Button
import discord
from datetime import datetime, timedelta
import logging
import re
import asyncio

# Lokale modules
from modules.dataStorage import load_tournament_data, save_tournament_data, load_config
from modules.utils import smart_send, get_player_team, get_team_open_matches
from modules.matchmaker import generate_weekend_slots
from modules.embeds import send_notify_team_members, send_request_reschedule, build_embed_from_template
from modules.logger import logger
from views.reschedule_view import RescheduleView
from modules.shared_states import pending_reschedules

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

# ---------------------------------------
# Command: /request_reschedule
# ---------------------------------------

@app_commands.command(name="request_reschedule", description="Fordere eine Neuansetzung für ein Match an.")
async def request_reschedule(interaction: Interaction, match_id: int, neuer_zeitpunkt: str):
    global pending_reschedules
    tournament = load_tournament_data()
    user_id = str(interaction.user.id)
    RESCHEDULE_TIMEOUT_HOURS = int(config.get("RESCHEDULE_TIMEOUT_HOURS", 24))

    # ➔ Team des Spielers ermitteln
    team_name = get_player_team(user_id)
    if not team_name:
        await interaction.response.send_message("🚫 Du bist in keinem Team registriert.", ephemeral=True)
        return

    # ➔ Offene Matches des Teams laden
    open_matches = get_team_open_matches(team_name)
    open_match_ids = [m["match_id"] for m in open_matches]

    # ➔ 1️⃣ Match-ID Prüfung
    if match_id not in open_match_ids:
        await interaction.response.send_message("🚫 Ungültige Match-ID oder nicht dein Match!", ephemeral=True)
        return

    # ➔ 2️⃣ Match bereits in pending_reschedules?
    if match_id in pending_reschedules:
        await interaction.response.send_message("🚫 Für dieses Match läuft bereits eine Reschedule-Anfrage!", ephemeral=True)
        return

    match = next((m for m in tournament.get("matches", []) if m.get("match_id") == match_id), None)
    if not match:
        await interaction.response.send_message("🚫 Match nicht gefunden.", ephemeral=True)
        return

    # ➔ 3️⃣ Neuer Zeitpunkt prüfen (Format, Zukunft, gültiger Slot)

    # Zeitformat prüfen
    try:
        new_dt = datetime.strptime(neuer_zeitpunkt, "%d.%m.%Y %H:%M")
    except ValueError:
        await interaction.response.send_message(
            "🚫 Ungültiges Datumsformat! Bitte wähle einen vorgeschlagenen Slot oder benutze `TT.MM.JJJJ HH:MM`.",
            ephemeral=True
        )
        return

    # In Zukunft?
    if new_dt <= datetime.now():
        await interaction.response.send_message(
            "🚫 Der neue Zeitpunkt muss in der Zukunft liegen!",
            ephemeral=True
        )
        return

    # Gültiger Slot?
    all_slots = generate_weekend_slots(tournament)
    booked_slots = set(m["scheduled_time"] for m in tournament.get("matches", []) if m.get("scheduled_time"))
    free_slots = [slot for slot in all_slots if slot not in booked_slots]
    future_slots = [datetime.fromisoformat(slot) for slot in free_slots if datetime.fromisoformat(slot) > datetime.now()]

    if new_dt not in future_slots:
        await interaction.response.send_message(
            "🚫 Der gewählte Zeitpunkt ist kein erlaubter freier Slot! Bitte wähle aus den vorgeschlagenen Optionen.",
            ephemeral=True
        )
        return

    # ➔ 4️⃣ Match-Start zu nah dran (weniger als 1h)?
    scheduled_time_str = match.get("scheduled_time")
    if scheduled_time_str:
        scheduled_dt = datetime.fromisoformat(scheduled_time_str)

    if scheduled_dt - datetime.utcnow() <= timedelta(hours=1):
        await interaction.response.send_message(
            "🚫 Du kannst Matches nur bis spätestens 1 Stunde vor geplantem Beginn verschieben.",
            ephemeral=True
        )
        return

    # ➔ 5️⃣ Anfrage starten
    pending_reschedules.add(match_id)
    interaction.client.loop.create_task(start_reschedule_timer(interaction.client, match_id))

    # ➔ Interaction defer sofort!
    await interaction.response.defer(ephemeral=True)

    # ➔ DMs verschicken und Channel informieren
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

    reschedule_channel = interaction.guild.get_channel(RESCHEDULE_CHANNEL_ID)
    if not reschedule_channel:
        await interaction.followup.send("🚫 Reschedule-Channel nicht gefunden.", ephemeral=True)
        return

    if not reschedule_channel.permissions_for(interaction.guild.me).send_messages:
        await interaction.followup.send("🚫 Ich habe keine Berechtigung, in den Reschedule-Channel zu schreiben!", ephemeral=True)
        return

    # ➔ DMs verschicken
    failed_members = []  # Liste für fehlgeschlagene DM-Versuche

    for member in valid_members:
        try:
            await send_request_reschedule(member, match_id, team1, team2, new_dt, [m.mention for m in valid_members])
        except discord.Forbidden:
            logger.warning(f"[RESCHEDULE] DM an {member.display_name} fehlgeschlagen.")
            failed_members.append(member)
        except Exception as e:
            logger.error(f"[RESCHEDULE] Fehler beim DM-Versand an {member.display_name}: {e}")
            failed_members.append(member)

    # ➔ Nur wenn mindestens eine DM fehlgeschlagen ist:
    if failed_members:
        # Kanal vorhanden und Bot hat Rechte wurde vorher geprüft
        mentions_failed = ", ".join([m.mention for m in failed_members])

        await send_request_reschedule(reschedule_channel, match_id, team1, team2, new_dt, [m.mention for m in valid_members])

        await reschedule_channel.send(f"⚠️ Konnte die folgenden Spieler nicht per DM erreichen: {mentions_failed}")

    # ➔ Am Ende optional kleines Confirm-Followup
    await interaction.followup.send("✅ Deine Reschedule-Anfrage wurde erstellt und die Beteiligten wurden benachrichtigt!", ephemeral=True)

    logger.info(f"[RESCHEDULE] Anfrage von {team_name} für Match {match_id} gestartet.")


# ---------------------------------------
# Autocomplete für Match-ID
# ---------------------------------------

@request_reschedule.autocomplete("match_id")
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
                    value=m["match_id"]
                )
            )
    return choices[:25]  # Discord erlaubt maximal 25 Vorschläge

# ---------------------------------------
# Helper: Autocomplete für neue Terminwahl
# ---------------------------------------

@request_reschedule.autocomplete("neuer_zeitpunkt")
async def neuer_zeitpunkt_autocomplete(interaction: Interaction, current: str):
    tournament = load_tournament_data()

    try:
        all_slots = generate_weekend_slots(tournament)
    except ValueError:
        # Falls noch keine Matches existieren ➔ einfach KEINE Vorschläge machen
        return []

    # Schon belegte Slots raussuchen
    booked_slots = set()
    for match in tournament.get("matches", []):
        if match.get("scheduled_time"):
            booked_slots.add(match["scheduled_time"])

    # Freie Slots herausfiltern
    free_slots = [slot for slot in all_slots if slot not in booked_slots]

    # 🔥 Jetzt: Nur Slots, die nach JETZT liegen
    free_slots = [
        slot for slot in free_slots
        if datetime.fromisoformat(slot) > datetime.now()
    ]

    if current:
        free_slots = [slot for slot in free_slots if current in slot]

    choices = []
    for slot in free_slots[:25]:
        dt = datetime.fromisoformat(slot)
        label = f"{dt.strftime('%A')} {dt.strftime('%d.%m.%Y %H:%M')} Uhr"  # Sichtbarer Text
        value = dt.strftime('%d.%m.%Y %H:%M')  # Tatsächlich übergebener Wert
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
        logger.info(f"[RESCHEDULE] Automatische Aufräumung: Match {match_id} wurde zurückgesetzt (Timeout nach {RESCHEDULE_TIMEOUT_HOURS} Stunden).")

        # ➔ Nachricht im Reschedule-Channel schicken
        reschedule_channel = bot.get_channel(RESCHEDULE_CHANNEL_ID)
        if reschedule_channel:
            await reschedule_channel.send(
                f"❗ Die Reschedule-Anfrage für Match `{match_id}` wurde automatisch beendet, da keine Einigung innerhalb von {RESCHEDULE_TIMEOUT_HOURS} Stunden erzielt wurde."
            )