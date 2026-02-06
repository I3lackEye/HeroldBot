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
from modules.config import CONFIG
from modules.dataStorage import load_tournament_data, save_tournament_data, RESCHEDULE_CHANNEL_ID
from modules.embeds import (
    build_embed_from_template,
    send_notify_team_members,
    send_request_reschedule,
    load_embed_template,
    get_message
)
from modules.logger import logger
from modules.matchmaker import generate_slot_matrix, get_valid_slots_for_match, assign_slots_with_matrix
from modules.task_manager import add_task, get_all_tasks
from modules.utils import (
    get_player_team,
    get_team_open_matches,
    smart_send,
    now_in_bot_timezone,
    ensure_timezone_aware,
    parse_iso_datetime,
    get_bot_timezone
)
from modules.reschedule_view import RescheduleView, SlotSelectView

# Global lock for reschedule operations
_reschedule_lock = asyncio.Lock()  # Prevent race conditions

RESCHEDULE_TIMEOUT_HOURS = CONFIG.tournament.reschedule_timeout_hours


# =======================================
# HELPER FUNCTIONS
# =======================================

def is_reschedule_pending_for_match(match_id: int) -> bool:
    """
    Checks if a reschedule is currently pending for the given match.
    Uses persisted JSON as single source of truth (no in-memory state).

    :param match_id: Match ID to check
    :return: True if reschedule is pending, False otherwise
    """
    tournament = load_tournament_data()
    match = next((m for m in tournament.get("matches", []) if m.get("match_id") == match_id), None)
    if not match:
        return False
    return match.get("reschedule_pending", False)


def get_reschedule_pending_matches() -> list:
    """
    Returns list of all matches with pending reschedule requests.
    Uses persisted JSON as single source of truth.

    :return: List of match dicts with reschedule_pending=True
    """
    tournament = load_tournament_data()
    return [m for m in tournament.get("matches", []) if m.get("reschedule_pending")]


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


def extend_tournament_and_reschedule_match(match: dict, days: int = 2, max_attempts: int = 3) -> bool:
    """
    Extends the tournament end date and tries to generate and assign new slots for the given match.
    Uses retry logic similar to matchmaker auto-extension.

    :param match: Match dict to reschedule
    :param days: Days to extend per attempt (default 2)
    :param max_attempts: Maximum extension attempts (default 3)
    :return: True if successful, otherwise False
    """
    tournament = load_tournament_data()
    end_str = tournament.get("tournament_end")

    try:
        current_end = parse_iso_datetime(end_str)
    except Exception as e:
        logger.error(f"[RESCHEDULE] ❌ Error reading tournament end time: {e}")
        return False

    original_end = current_end
    match_id = match.get("match_id")

    for attempt in range(1, max_attempts + 1):
        logger.info(f"[RESCHEDULE-EXTEND] 🔄 Extension attempt {attempt}/{max_attempts} for match {match_id}")

        # Extend tournament
        new_end = current_end + timedelta(days=days)
        tournament["tournament_end"] = new_end.isoformat()
        logger.warning(f"[RESCHEDULE-EXTEND] ⏰ Tournament end extended: {current_end.date()} → {new_end.date()} (+{days} days)")

        # Reset match scheduled_time
        match["scheduled_time"] = None

        # Try to reschedule this match
        slot_matrix = generate_slot_matrix(tournament)
        updated_matches, unassigned = assign_slots_with_matrix([match], slot_matrix)
        success = len(unassigned) == 0

        if success:
            save_tournament_data(tournament)
            logger.info(f"[RESCHEDULE-EXTEND] ✅ Match {match_id} successfully scheduled after extension (attempt {attempt})")
            total_extension_days = (new_end - original_end).days
            logger.info(f"[RESCHEDULE-EXTEND] 📊 Total tournament extension: +{total_extension_days} days")
            return True
        else:
            logger.warning(f"[RESCHEDULE-EXTEND] ⚠️  Attempt {attempt} failed - no slot found despite extension")
            # Prepare for next iteration
            current_end = new_end

    # All attempts exhausted
    logger.error(f"[RESCHEDULE-EXTEND] ❌ Failed to schedule match {match_id} after {max_attempts} extension attempts")
    total_extension_days = (current_end - original_end).days
    logger.error(f"[RESCHEDULE-EXTEND] Tournament was extended by {total_extension_days} days total, but no slot could be found")

    # Save the extended tournament even though scheduling failed
    save_tournament_data(tournament)

    return False


# ---------------------------------------
# Command: /request_reschedule
# ---------------------------------------
async def handle_request_reschedule(interaction: Interaction, match_id: int):
    """
    Handles a reschedule request from a player.
    Shows available slots for the player to choose from.
    """
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

    match = next((m for m in tournament.get("matches", []) if m.get("match_id") == match_id), None)
    if not match:
        await interaction.response.send_message(get_message("ERRORS", "match_not_found"), ephemeral=True)
        return

    # Check if reschedule is already pending (persisted state)
    if match.get("reschedule_pending"):
        await interaction.response.send_message(
            "🚫 A reschedule request is already pending for this match!", ephemeral=True
        )
        return

    # Check if this team has already requested a reschedule for this match
    reschedule_requested_by = match.get("reschedule_requested_by", [])
    if team_name in reschedule_requested_by:
        await interaction.response.send_message(
            "🚫 Your team has already requested a reschedule for this match.\n"
            "Each team can only request one reschedule per match.",
            ephemeral=True
        )
        return

    logger.info(f"[RESCHEDULE] Open match IDs for {team_name}: {open_match_ids}")

    # 2️⃣ Find available slots
    allowed_slots = get_free_slots_for_match(tournament, match_id)
    logger.debug(f"[RESCHEDULE] get_free_slots_for_match returned: {allowed_slots}")

    if not allowed_slots:
        logger.warning(f"[RESCHEDULE] No free slots found – trying to extend tournament.")
        success = extend_tournament_and_reschedule_match(match, days=2)
        if not success:
            await interaction.response.send_message(
                "🚫 No valid slots available – even after extension. Please contact tournament management.",
                ephemeral=True
            )
            return

        # Reload after extension
        tournament = load_tournament_data()
        match = next((m for m in tournament.get("matches", []) if m.get("match_id") == match_id), None)
        allowed_slots = get_free_slots_for_match(tournament, match_id)

        if not allowed_slots:
            await interaction.response.send_message(
                "❌ Even after extension, no free slots could be found.",
                ephemeral=True
            )
            return

    # Filter to only future slots
    now = now_in_bot_timezone()
    future_slots = [slot for slot in allowed_slots if slot > now]

    if not future_slots:
        await interaction.response.send_message(
            "❌ No future slots available for reschedule.",
            ephemeral=True
        )
        return

    # Sort slots chronologically
    future_slots.sort()
    logger.info(f"[RESCHEDULE] Found {len(future_slots)} available future slots for match {match_id}")

    # Check if too late (match too close to start)
    scheduled_time_str = match.get("scheduled_time")
    if scheduled_time_str:
        try:
            scheduled_dt = parse_iso_datetime(scheduled_time_str)
            logger.debug(f"[RESCHEDULE] Scheduled time from match: {scheduled_dt.isoformat()}")
            if scheduled_dt - now_in_bot_timezone() <= timedelta(hours=24):
                await interaction.response.send_message(
                    "🚫 You can only reschedule matches up to 24 hours before the scheduled start.",
                    ephemeral=True
                )
                return
        except Exception as e:
            logger.error(f"[RESCHEDULE] ❌ Error parsing scheduled_time: {scheduled_time_str} – {e}")

    # 3️⃣ Show slot selection to requester
    async def post_reschedule_request(slot_interaction: Interaction, selected_slot: datetime):
        """Callback called when player selects a slot."""
        # Get match data
        team1 = match["team1"]
        team2 = match["team2"]
        members1 = tournament.get("teams", {}).get(team1, {}).get("members", [])
        members2 = tournament.get("teams", {}).get(team2, {}).get("members", [])
        mentions = members1 + members2

        # Fetch valid members
        from modules.utils import extract_user_id
        valid_members = []
        for mention in mentions:
            try:
                uid = extract_user_id(mention)
                if uid:
                    member = await interaction.guild.fetch_member(uid)
                    valid_members.append(member)
                else:
                    logger.warning(f"[RESCHEDULE] ⚠️ Could not extract user ID from mention: {mention}")
            except discord.NotFound:
                logger.warning(f"[RESCHEDULE] ⚠️ Member {uid} not found.")
            except discord.Forbidden:
                logger.error(f"[RESCHEDULE] ❌ No permission to fetch member {uid}.")
            except Exception as e:
                logger.error(f"[RESCHEDULE] ❌ Error fetching member {uid}: {e}")

        if not valid_members:
            logger.error(f"[RESCHEDULE] No valid members found for match {match_id}")
            return

        # Build embed
        deadline = (now_in_bot_timezone() + timedelta(hours=RESCHEDULE_TIMEOUT_HOURS)).strftime("%d.%m.%Y %H:%M")
        short_players = "\n".join([m.mention for m in valid_members][:10])  # Max 10 for readability
        short_match = f"{team1[:50]} vs {team2[:50]}"

        placeholders = {
            "MATCH_INFO": short_match,
            "NEW_SLOT": selected_slot.strftime("%d.%m.%Y %H:%M"),
            "DEADLINE": deadline,
            "PLAYERS": short_players
        }

        try:
            templates = load_embed_template("reschedule")
            template = templates.get("RESCHEDULE")
            final_embed = build_embed_from_template(template, placeholders)
        except Exception as e:
            logger.error(f"[RESCHEDULE] ❌ Error building embed: {e}")
            await slot_interaction.followup.send(get_message("ERRORS", "embed_error"), ephemeral=True)
            return

        # Mark that this team has requested a reschedule for this match
        tournament_updated = load_tournament_data()
        match_updated = next((m for m in tournament_updated.get("matches", []) if m.get("match_id") == match_id), None)
        if match_updated:
            reschedule_requested_by = match_updated.get("reschedule_requested_by", [])
            if team_name not in reschedule_requested_by:
                reschedule_requested_by.append(team_name)
                match_updated["reschedule_requested_by"] = reschedule_requested_by

            # Mark reschedule as pending (persisted state for bot restart resilience)
            match_updated["reschedule_pending"] = True
            match_updated["reschedule_pending_since"] = now_in_bot_timezone().isoformat()

            save_tournament_data(tournament_updated)
            logger.info(f"[RESCHEDULE] Marked {team_name} as having requested reschedule for match {match_id}")
            logger.info(f"[RESCHEDULE] Set reschedule_pending=True for match {match_id}")

        # Post in reschedule channel
        channel = interaction.guild.get_channel(RESCHEDULE_CHANNEL_ID)
        if not channel:
            logger.error(f"[RESCHEDULE] Reschedule channel not found (ID: {RESCHEDULE_CHANNEL_ID})")
            return

        view = RescheduleView(match_id, team1, team2, selected_slot, valid_members, interaction.user)
        try:
            msg = await channel.send(embed=final_embed, view=view)
            view.message = msg
            logger.info(f"[RESCHEDULE] Request for match {match_id} posted in #{channel.name}")
        except Exception as e:
            logger.error(f"[RESCHEDULE] ❌ Error posting request: {e}")
            return

        # Start timer and register in task manager
        timer_task = interaction.client.loop.create_task(start_reschedule_timer(interaction.client, match_id))
        add_task(f"reschedule_timer_match_{match_id}", timer_task)
        logger.debug(f"[RESCHEDULE] Timer task created and registered for match {match_id}")

    # Show slot selection view
    view = SlotSelectView(match_id, interaction.user, future_slots, post_reschedule_request)
    await interaction.response.send_message(
        f"🔄 **Reschedule Request for Match {match_id}**\n"
        f"Select a new time slot from the dropdown below:\n"
        f"_({len(future_slots)} slots available)_",
        view=view,
        ephemeral=True
    )




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


async def start_reschedule_timer(bot, match_id: int, delay_seconds: int = None):
    """
    Waits a certain time and then automatically removes the reschedule request.
    Optionally notifies the reschedule channel.
    Can be cancelled early if reschedule is resolved before timeout.

    :param bot: Bot instance
    :param match_id: Match ID for reschedule
    :param delay_seconds: Optional custom delay (for timer recovery). Defaults to RESCHEDULE_TIMEOUT_HOURS
    """
    try:
        if delay_seconds is None:
            delay_seconds = RESCHEDULE_TIMEOUT_HOURS * 3600

        await asyncio.sleep(delay_seconds)

        # Clean up reschedule state in JSON
        async with _reschedule_lock:
            tournament = load_tournament_data()
            match = next((m for m in tournament.get("matches", []) if m.get("match_id") == match_id), None)

            if match and match.get("reschedule_pending"):
                # Clear reschedule flags
                if "reschedule_pending" in match:
                    del match["reschedule_pending"]
                if "reschedule_requested_by" in match:
                    del match["reschedule_requested_by"]
                if "reschedule_pending_since" in match:
                    del match["reschedule_pending_since"]

                save_tournament_data(tournament)
                logger.info(
                    f"[RESCHEDULE] Automatic cleanup: Match {match_id} was reset (timeout after {delay_seconds/3600:.1f} hours)."
                )

                # Send message in reschedule channel
                reschedule_channel = bot.get_channel(RESCHEDULE_CHANNEL_ID)
                if reschedule_channel:
                    await reschedule_channel.send(
                        f"❗ The reschedule request for match `{match_id}` was automatically ended as no agreement was reached within {RESCHEDULE_TIMEOUT_HOURS} hours."
                    )
    except asyncio.CancelledError:
        logger.debug(f"[RESCHEDULE] Timer for match {match_id} was cancelled (reschedule resolved early)")
        # Don't propagate the exception, just exit cleanly
        pass
