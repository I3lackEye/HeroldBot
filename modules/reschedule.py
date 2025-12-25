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

# Local modules
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
# Helper: Extract IDs
# ---------------------------------------
def extract_ids(members):
    """Extracts user IDs from mention strings."""
    ids = []
    for m in members:
        match = re.search(r"\d+", m)
        if match:
            ids.append(match.group(0))
    return ids


def get_free_slots_for_match(tournament, match_id: int) -> list[datetime]:
    """
    Returns all allowed and free slots for a specific match.
    """
    match = next((m for m in tournament.get("matches", []) if m["match_id"] == match_id), None)
    if not match:
        return []

    team1 = match["team1"]
    team2 = match["team2"]
    slot_matrix = generate_slot_matrix(tournament)

    all_valid = get_valid_slots_for_match(team1, team2, slot_matrix)

    # Remove already booked slots
    booked = {
        m["scheduled_time"]
        for m in tournament["matches"]
        if isinstance(m.get("scheduled_time"), str) and "T" in m["scheduled_time"]
    }
    return [slot for slot in all_valid if slot.isoformat() not in booked]


def extend_tournament_and_reschedule_match(match: dict, days: int = 2) -> bool:
    """
    Extends the tournament end date and tries to generate and assign new slots for the given match.
    Returns True if successful, otherwise False.
    """
    tournament = load_tournament_data()
    end_str = tournament.get("tournament_end")

    try:
        current_end = datetime.fromisoformat(end_str).astimezone(ZoneInfo("UTC"))
    except Exception as e:
        logger.error(f"[RESCHEDULE] ❌ Error reading tournament end time: {e}")
        return False

    new_end = current_end + timedelta(days=days)
    tournament["tournament_end"] = new_end.isoformat()
    logger.warning(f"[RESCHEDULE] ⚠️ Tournament end extended to {new_end.isoformat()}.")

    # Reset match
    match["scheduled_time"] = None

    # Reschedule only this match
    slot_matrix = generate_slot_matrix(tournament)
    success = not assign_slots_with_matrix([match], slot_matrix)[1]
    save_tournament_data(tournament)

    if success:
        logger.info(f"[RESCHEDULE] ✅ New slot assigned for match {match['match_id']} after extension.")
    else:
        logger.warning(f"[RESCHEDULE] ❌ No slot found despite tournament extension.")

    return success


# ---------------------------------------
# Command: /request_reschedule
# ---------------------------------------
async def handle_request_reschedule(interaction: Interaction, match_id: int):
    """
    Handles a reschedule request from a player.
    Validates the request, finds free slots, and posts a voting message.
    """
    global pending_reschedules
    tournament = load_tournament_data()
    user_id = str(interaction.user.id)
    logger.info(f"[RESCHEDULE] Request received from {interaction.user.display_name} for match ID {match_id}")



    # 1️⃣ Check team and match
    team_name = get_player_team(user_id)
    if not team_name:
        await interaction.response.send_message("🚫 You are not registered in any team.", ephemeral=True)
        return


    open_matches = get_team_open_matches(team_name)
    open_match_ids = [m["match_id"] for m in open_matches]

    if match_id not in open_match_ids:
        await interaction.response.send_message("🚫 Invalid match ID or not your match!", ephemeral=True)
        return

    if match_id in pending_reschedules:
        await interaction.response.send_message(
            "🚫 A reschedule request is already pending for this match!", ephemeral=True
        )
        return

    match = next((m for m in tournament.get("matches", []) if m.get("match_id") == match_id), None,)
    if not match:
        await interaction.response.send_message("🚫 Match not found.", ephemeral=True)
        return
    if match.get("rescheduled_once", False):
        await interaction.response.send_message("🚫 This match has already been rescheduled and cannot be rescheduled again.", ephemeral=True)
        return
    logger.info(f"[RESCHEDULE] Open match IDs for {team_name}: {open_match_ids}")

    # 2️⃣ Automatically determine next free slot
    allowed_slots = get_free_slots_for_match(tournament, match_id)
    logger.debug(f"[RESCHEDULE] get_free_slots_for_match returned: {allowed_slots}")
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
            logger.error(f"[RESCHEDULE] Invalid slot in free_slots: {slot} – Error: {e}")

    if not future_slots:
        logger.warning(f"[RESCHEDULE] No free slots – tournament will be extended.")
        success = extend_tournament_and_reschedule_match(match, days=2)
        if not success:
            await interaction.response.send_message(
                "🚫 No valid slot available – even after extension. Please inform tournament management.",
                ephemeral=True
            )
            return
        logger.debug(f"[RESCHEDULE] ISO slots: {allowed_iso}")
        logger.debug(f"[RESCHEDULE] Booked slots: {booked_slots}")
        logger.debug(f"[RESCHEDULE] Free slots after filter: {free_slots}")
        logger.debug(f"[RESCHEDULE] Future slots: {future_slots}")

        # Reload
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
                "❌ Even after extension, no free slot could be found.",
                ephemeral=True
            )
            return

    logger.debug(f"[RESCHEDULE] Future slot candidates: {[s.isoformat() for s in future_slots]}")
    # ⏰ Take next slot
    new_dt = min(future_slots)

    # Check if too late (match too close to start)
    scheduled_time_str = match.get("scheduled_time")
    if scheduled_time_str:
        try:
            scheduled_dt = datetime.fromisoformat(scheduled_time_str)
            logger.debug(f"[RESCHEDULE] Scheduled time from match: {scheduled_dt.isoformat()}")
            if scheduled_dt - datetime.now(ZoneInfo("UTC")) <= timedelta(hours=1):
                await interaction.response.send_message(
                    "🚫 You can only reschedule matches up to 1 hour before the scheduled start.",
                    ephemeral=True
                )
                return
        except Exception as e:
            logger.error(f"[RESCHEDULE] ❌ Error parsing scheduled_time: {scheduled_time_str} – {e}")



    # 3️⃣ Prepare players for voting
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
                logger.warning(f"[RESCHEDULE] ⚠️ Member {uid} not found.")
            except discord.Forbidden:
                logger.error(f"[RESCHEDULE] ❌ No permission to fetch member {uid}.")
            except Exception as e:
                logger.error(f"[RESCHEDULE] ❌ Error fetching member {uid}: {e}")


    logger.debug(f"[RESCHEDULE] Valid members for match {match_id}: {[m.display_name for m in valid_members]}")

    if not valid_members:
        await interaction.response.send_message("❌ No valid players found.", ephemeral=True)
        return

    # 4️⃣ Create request embed
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
    logger.debug(f"[RESCHEDULE] Embed preview: {placeholders}")
    logger.debug(f"[RESCHEDULE] Embed will be sent to channel ID {RESCHEDULE_CHANNEL_ID}")

    try:
        templates = load_embed_template("reschedule")
        if not isinstance(templates, dict):
            raise TypeError("load_embed_template did not return a dict")

        template = templates.get("RESCHEDULE")
        if not isinstance(template, dict):
            raise TypeError("RESCHEDULE block missing or not a dict")

    except Exception as e:
        logger.error(f"[RESCHEDULE] ❌ Error loading embed template: {e}")
        await interaction.followup.send("❌ Embed template could not be loaded.", ephemeral=True)
        return

    try:
        final_embed = build_embed_from_template(template, placeholders)
        logger.info(f"[RESCHEDULE] Embed successfully built. Sending to channel ID {RESCHEDULE_CHANNEL_ID}")
    except Exception as e:
        logger.error(f"[RESCHEDULE] ❌ Error building embed: {e}")
        await interaction.followup.send("❌ Internal error creating embed. Please inform tournament management.", ephemeral=True)
        return


    # 5️⃣ Post request in channel
    channel = interaction.guild.get_channel(RESCHEDULE_CHANNEL_ID)
    if not channel:
        await interaction.response.send_message("❌ Reschedule channel not found.", ephemeral=True)
        return
    logger.debug(f"[RESCHEDULE] Channel is: {channel} (Type: {type(channel)})")

    view = RescheduleView(match_id, team1, team2, new_dt, valid_members)
    logger.debug(f"[RESCHEDULE] Sending to channel {channel.name} ({channel.id}) with view: {view}")
    try:
        logger.debug(f"[RESCHEDULE] Channel permissions for bot in #{channel.name}: {channel.permissions_for(interaction.guild.me)}")
        msg = await channel.send(embed=final_embed, view=view)
        view.message = msg
        logger.info(f"[RESCHEDULE] Request for match {match_id} successfully posted in channel #{channel.name}.")
    except discord.HTTPException as e:
        logger.error(f"[RESCHEDULE] ❌ Discord HTTPException sending request: {e.text} – {e.code}")
        await interaction.followup.send("❌ Discord rejected sending the request (HTTPException).", ephemeral=True)
        return
    except Exception as e:
        logger.error(f"[RESCHEDULE] ❌ General error sending request: {e}")
        await interaction.followup.send("❌ Error sending request. Please inform tournament management.", ephemeral=True)
        return


    # 6️⃣ Confirmation to user
    try:
        await interaction.response.send_message("✅ Your request has been started in the reschedule channel!", ephemeral=True)
    except discord.errors.InteractionResponded:
        await interaction.followup.send("✅ Your request has been started in the reschedule channel!", ephemeral=True)

    # 7️⃣ Start reschedule
    pending_reschedules.add(match_id)
    interaction.client.loop.create_task(start_reschedule_timer(interaction.client, match_id))




# ---------------------------------------
# Autocomplete for Match ID
# ---------------------------------------
async def match_id_autocomplete(interaction: Interaction, current: str):
    """Provides autocomplete suggestions for match IDs."""
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
    return choices[:25]  # Discord allows max 25 suggestions


# ---------------------------------------
# Helper: Autocomplete for new time selection
# ---------------------------------------
async def neuer_zeitpunkt_autocomplete(interaction: Interaction, current: str):
    """Provides autocomplete suggestions for available time slots."""
    tournament = load_tournament_data()

    try:
        allowed_slots = get_free_slots_for_match(tournament, match_id)
        allowed_iso = {slot.isoformat() for slot in allowed_slots}

    except ValueError:
        return []

    # Find already booked slots
    booked_slots = set()
    for match in tournament.get("matches", []):
        if match.get("scheduled_time"):
            booked_slots.add(match["scheduled_time"])

    # Only allowed & free slots
    free_slots = [slot for slot in allowed_iso if slot not in booked_slots]

    # Only future slots
    free_slots = [slot for slot in free_slots if datetime.fromisoformat(slot) > datetime.now()]

    if current:
        free_slots = [slot for slot in free_slots if current in slot]

    choices = []
    for slot in free_slots[:25]:
        dt = datetime.fromisoformat(slot)
        label = f"{dt.strftime('%A')} {dt.strftime('%d.%m.%Y %H:%M')}"
        value = dt.strftime("%d.%m.%Y %H:%M")
        choices.append(app_commands.Choice(name=label, value=value))

    return choices


async def start_reschedule_timer(bot, match_id: int):
    """
    Waits a certain time and then automatically removes the reschedule request.
    Optionally notifies the reschedule channel.
    """
    await asyncio.sleep(RESCHEDULE_TIMEOUT_HOURS * 3600)  # Wait for timeout

    if match_id in pending_reschedules:
        pending_reschedules.discard(match_id)
        logger.info(
            f"[RESCHEDULE] Automatic cleanup: Match {match_id} was reset (timeout after {RESCHEDULE_TIMEOUT_HOURS} hours)."
        )

        # ➔ Send message in reschedule channel
        reschedule_channel = bot.get_channel(RESCHEDULE_CHANNEL_ID)
        if reschedule_channel:
            await reschedule_channel.send(
                f"❗ The reschedule request for match `{match_id}` was automatically ended as no agreement was reached within {RESCHEDULE_TIMEOUT_HOURS} hours."
            )
