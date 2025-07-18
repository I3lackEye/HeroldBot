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
from modules.dataStorage import load_config, load_tournament_data, save_tournament_data, RESCHEDULE_CHANNEL_ID
from modules.embeds import (
    build_embed_from_template,
    send_notify_team_members,
    send_request_reschedule,
    load_embed_template
)
from modules.logger import logger
from modules.matchmaker import generate_slot_matrix, get_valid_slots_for_match, assign_slots_with_matrix
from modules.shared_states import pending_reschedules
from modules.utils import get_player_team, get_team_open_matches, smart_send
from views.reschedule_view import RescheduleView

config = load_config()
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
    booked = {
        m["scheduled_time"]
        for m in tournament["matches"]
        if isinstance(m.get("scheduled_time"), str) and "T" in m["scheduled_time"]
    }
    return [slot for slot in all_valid if slot.isoformat() not in booked]


def extend_tournament_and_reschedule_match(match: dict, days: int = 2) -> bool:
    """
    Verlängert das Turnierende und versucht, für das gegebene Match neue Slots zu generieren und zuzuweisen.
    Gibt True zurück, wenn erfolgreich, sonst False.
    """
    tournament = load_tournament_data()
    end_str = tournament.get("tournament_end")

    try:
        current_end = datetime.fromisoformat(end_str).astimezone(ZoneInfo("UTC"))
    except Exception as e:
        logger.error(f"[RESCHEDULE] ❌ Fehler beim Lesen des Turnierende-Zeitpunkts: {e}")
        return False

    new_end = current_end + timedelta(days=days)
    tournament["tournament_end"] = new_end.isoformat()
    logger.warning(f"[RESCHEDULE] ⚠️ Turnierende wurde auf {new_end.isoformat()} verlängert.")

    # Match zurücksetzen
    match["scheduled_time"] = None

    # Nur dieses Match erneut einplanen
    # Nur dieses Match erneut einplanen
    slot_matrix = generate_slot_matrix(tournament)
    success = not assign_slots_with_matrix([match], slot_matrix)[1]
    save_tournament_data(tournament)

    if success:
        logger.info(f"[RESCHEDULE] ✅ Neuer Slot für Match {match['match_id']} nach Erweiterung zugewiesen.")
    else:
        logger.warning(f"[RESCHEDULE] ❌ Kein Slot gefunden trotz Turnierverlängerung.")

    return success


# ---------------------------------------
# Command: /request_reschedule
# ---------------------------------------
async def handle_request_reschedule(interaction: Interaction, match_id: int):
    global pending_reschedules
    tournament = load_tournament_data()
    user_id = str(interaction.user.id)
    logger.info(f"[RESCHEDULE] Anfrage empfangen von {interaction.user.display_name} für Match-ID {match_id}")



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

    match = next((m for m in tournament.get("matches", []) if m.get("match_id") == match_id), None,)
    if not match:
        await interaction.response.send_message("🚫 Match nicht gefunden.", ephemeral=True)
        return
    if match.get("rescheduled_once", False):
        await interaction.response.send_message("🚫 Dieses Match wurde bereits verschoben und kann nicht erneut verschoben werden.", ephemeral=True)
        return
    logger.info(f"[RESCHEDULE] Open Match IDs für {team_name}: {open_match_ids}")

    # 2️⃣ Automatisch nächsten freien Slot ermitteln
    allowed_slots = get_free_slots_for_match(tournament, match_id)
    logger.debug(f"[RESCHEDULE] get_free_slots_for_match lieferte: {allowed_slots}")
    allowed_iso = {slot.isoformat() for slot in allowed_slots}
    booked_slots = {m["scheduled_time"] for m in tournament["matches"] if m.get("scheduled_time")}
    free_slots = [slot for slot in allowed_iso if slot not in booked_slots]

    now = datetime.now(ZoneInfo("Europe/Berlin"))
    future_slots = []
    for slot in free_slots:
        try:
            dt = datetime.fromisoformat(slot).astimezone(ZoneInfo("Europe/Berlin"))
            if dt > now:
                future_slots.append(dt)
        except Exception as e:
            logger.error(f"[RESCHEDULE] Ungültiger Slot in free_slots: {slot} – Fehler: {e}")

    if not future_slots:
        logger.warning(f"[RESCHEDULE] Keine freien Slots – Turnier wird erweitert.")
        success = extend_tournament_and_reschedule_match(match, days=2)
        if not success:
            await interaction.response.send_message(
                "🚫 Kein gültiger Slot mehr verfügbar – auch nach Verlängerung. Bitte Turnierleitung informieren.",
                ephemeral=True
            )
            return
        logger.debug(f"[RESCHEDULE] ISO-Slots: {allowed_iso}")
        logger.debug(f"[RESCHEDULE] Gebuchte Slots: {booked_slots}")
        logger.debug(f"[RESCHEDULE] Freie Slots nach Filter: {free_slots}")
        logger.debug(f"[RESCHEDULE] Zukünftige Slots: {future_slots}")

        # Neu laden
        tournament = load_tournament_data()
        match = next((m for m in tournament.get("matches", []) if m.get("match_id") == match_id), None)
        allowed_slots = get_free_slots_for_match(tournament, match_id)
        allowed_iso = {slot.isoformat() for slot in allowed_slots}
        booked_slots = {m["scheduled_time"] for m in tournament["matches"] if m.get("scheduled_time")}
        free_slots = [slot for slot in allowed_iso if slot not in booked_slots]

        future_slots = [
            datetime.fromisoformat(slot).astimezone(ZoneInfo("Europe/Berlin"))
            for slot in free_slots
            if datetime.fromisoformat(slot).astimezone(ZoneInfo("Europe/Berlin")) > now
        ]

        if not future_slots:
            await interaction.response.send_message(
                "❌ Auch nach Erweiterung konnte kein freier Slot gefunden werden.",
                ephemeral=True
            )
            return

    logger.debug(f"[RESCHEDULE] Zukünftige Slot-Kandidaten: {[s.isoformat() for s in future_slots]}")
    # ⏰ Nächsten Slot nehmen
    new_dt = min(future_slots)

    # Prüfe ob zu spät (Match zu nah am Start)
    scheduled_time_str = match.get("scheduled_time")
    if scheduled_time_str:
        try:
            scheduled_dt = datetime.fromisoformat(scheduled_time_str)
            logger.debug(f"[RESCHEDULE] Geplanter Zeitpunkt laut Match: {scheduled_dt.isoformat()}")
            if scheduled_dt - datetime.now(ZoneInfo("UTC")) <= timedelta(hours=1):
                await interaction.response.send_message(
                    "🚫 Du kannst Matches nur bis spätestens 1 Stunde vor geplantem Beginn verschieben.",
                    ephemeral=True
                )
                return
        except Exception as e:
            logger.error(f"[RESCHEDULE] ❌ Fehler beim Parsen von scheduled_time: {scheduled_time_str} – {e}")



    # 3️⃣ Spieler für Abstimmung vorbereiten
    team1 = match["team1"]
    team2 = match["team2"]
    members1 = tournament.get("teams", {}).get(team1, {}).get("members", [])
    members2 = tournament.get("teams", {}).get(team2, {}).get("members", [])
    mentions = members1 + members2

    valid_members = []
    for mention in mentions:
        if mention.startswith("<@"):
            try:
                uid = int(mention.replace("<@", "").replace("!", "").replace(">", ""))
                member = await interaction.guild.fetch_member(uid)
                valid_members.append(member)
            except discord.NotFound:
                logger.warning(f"[RESCHEDULE] ⚠️ Member {uid} nicht gefunden.")
            except discord.Forbidden:
                logger.error(f"[RESCHEDULE] ❌ Keine Rechte, um Member {uid} zu fetchen.")
            except Exception as e:
                logger.error(f"[RESCHEDULE] ❌ Fehler beim Holen von Member {uid}: {e}")


    logger.debug(f"[RESCHEDULE] Valid Members für Match {match_id}: {[m.display_name for m in valid_members]}")

    if not valid_members:
        await interaction.response.send_message("❌ Keine gültigen Spieler gefunden.", ephemeral=True)
        return

    # 4️⃣ Anfrage-Embed erstellen
    deadline = (datetime.now(ZoneInfo("Europe/Berlin")) + timedelta(hours=RESCHEDULE_TIMEOUT_HOURS)).strftime("%d.%m.%Y %H:%M")
    def shorten_lines(lines, max_total=1000):
        result = []
        total = 0
        for line in lines:
            if total + len(line) > max_total:
                result.append("…")
                break
            result.append(line)
            total += len(line)
        return "\n".join(result)

    short_players = shorten_lines([m.mention for m in valid_members])
    short_match = f"{team1[:50]} vs {team2[:50]}"

    placeholders = {
        "MATCH_INFO": short_match,
        "NEW_SLOT": new_dt.strftime("%d.%m.%Y %H:%M"),
        "DEADLINE": deadline,
        "PLAYERS": short_players
    }
    logger.debug(f"[RESCHEDULE] Embed-Preview: {placeholders}")
    logger.debug(f"[RESCHEDULE] Embed wird versucht zu verschicken in Channel-ID {RESCHEDULE_CHANNEL_ID}")

    try:
        templates = load_embed_template("reschedule")
        if not isinstance(templates, dict):
            raise TypeError("load_embed_template hat kein dict geliefert")

        template = templates.get("RESCHEDULE")
        if not isinstance(template, dict):
            raise TypeError("RESCHEDULE-Block fehlt oder ist kein dict")

    except Exception as e:
        logger.error(f"[RESCHEDULE] ❌ Fehler beim Laden des Embed-Templates: {e}")
        await interaction.followup.send("❌ Embed-Vorlage konnte nicht geladen werden.", ephemeral=True)
        return

    try:
        final_embed = build_embed_from_template(template, placeholders)
        logger.info(f"[RESCHEDULE] Embed erfolgreich gebaut. Sende in Channel-ID {RESCHEDULE_CHANNEL_ID}")
    except Exception as e:
        logger.error(f"[RESCHEDULE] ❌ Fehler beim Bauen des Embeds: {e}")
        await interaction.followup.send("❌ Interner Fehler beim Erstellen des Embeds. Bitte Turnierleitung informieren.", ephemeral=True)
        return


    # 5️⃣ Anfrage im Channel posten
    channel = interaction.guild.get_channel(RESCHEDULE_CHANNEL_ID)
    if not channel:
        await interaction.response.send_message("❌ Reschedule-Channel nicht gefunden.", ephemeral=True)
        return
    logger.debug(f"[RESCHEDULE] Channel ist: {channel} (Typ: {type(channel)})")

    view = RescheduleView(match_id, team1, team2, new_dt, valid_members)
    logger.debug(f"[RESCHEDULE] Sende an Channel {channel.name} ({channel.id}) mit View: {view}")
    try:
        logger.debug(f"[RESCHEDULE] Channel Permissions für Bot in #{channel.name}: {channel.permissions_for(interaction.guild.me)}")
        msg = await channel.send(embed=final_embed, view=view)
        view.message = msg
        logger.info(f"[RESCHEDULE] Anfrage für Match {match_id} erfolgreich im Channel #{channel.name} gepostet.")
    except discord.HTTPException as e:
        logger.error(f"[RESCHEDULE] ❌ Discord HTTPException beim Senden der Anfrage: {e.text} – {e.code}")
        await interaction.followup.send("❌ Discord hat das Senden der Anfrage abgelehnt (HTTPException).", ephemeral=True)
        return
    except Exception as e:
        logger.error(f"[RESCHEDULE] ❌ Allgemeiner Fehler beim Senden der Anfrage: {e}")
        await interaction.followup.send("❌ Fehler beim Senden der Anfrage. Bitte Turnierleitung informieren.", ephemeral=True)
        return


    # 6️⃣ Bestätigung an User
    try:
        await interaction.response.send_message("✅ Deine Anfrage wurde im Reschedule-Channel gestartet!", ephemeral=True)
    except discord.errors.InteractionResponded:
        await interaction.followup.send("✅ Deine Anfrage wurde im Reschedule-Channel gestartet!", ephemeral=True)

    # 7️⃣ Reschedule starten
    pending_reschedules.add(match_id)
    interaction.client.loop.create_task(start_reschedule_timer(interaction.client, match_id))




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
