# modules/tournament.py

import asyncio
import re
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import discord
from discord import Embed, Interaction, app_commands

# Local modules
from modules import poll
from modules.archive import archive_current_tournament, update_tournament_history
from modules.config import CONFIG
from modules.dataStorage import (
    delete_tournament_file,
    load_games,
    load_global_data,
    load_tournament_data,
    reset_tournament,
    save_tournament_data,
)
from modules.embeds import (
    build_embed_from_template,
    load_embed_template,
    send_list_matches,
    send_match_schedule_for_channel,
    send_registration_closed,
    send_tournament_announcement,
    send_tournament_end_announcement,
    get_message,
)
from modules.logger import logger
from modules.matchmaker import (
    auto_match_solo,
    cleanup_orphan_teams,
    create_round_robin_schedule,
    generate_and_assign_slots,
    generate_schedule_overview,
)
from modules.info import (
    get_mvp,
    get_winner_ids,
    get_winner_team,
)
from modules.stats_tracker import (
    record_match_result,
    update_tournament_participation,
    update_tournament_wins
)
from modules.task_manager import add_task
from modules.utils import (
    all_matches_completed,
    autocomplete_teams,
    calculate_optimal_tournament_duration,
    get_current_chosen_game,
    get_player_team,
    has_permission,
    smart_send,
)

# Global variables for double-call prevention
_registration_closed = False
_registration_lock = asyncio.Lock()  # Prevent race conditions


# ---------------------------------------
# Helper Functions
# ---------------------------------------
async def end_tournament_procedure(
    channel: discord.TextChannel,
    manual_trigger: bool = False,
    interaction: Optional[Interaction] = None,
    bot: Optional[discord.Client] = None,
):
    """
    Handles the tournament end procedure:
    - Archives tournament data
    - Updates statistics
    - Resets tournament state
    - Announces results
    """
    tournament = load_tournament_data()

    if not manual_trigger and not all_matches_completed():
        logger.info("[TOURNAMENT] Not all matches completed. Aborting automatic end.")
        await channel.send(get_message("ERRORS", "matches_incomplete"))
        return

    # Archive tournament data
    try:
        archive_path = archive_current_tournament()
        logger.info(f"[TOURNAMENT] Tournament successfully archived to: {archive_path}")
    except Exception as e:
        logger.error(f"[TOURNAMENT] Error archiving tournament: {e}")

    # Winners, MVP, etc.
    winner_ids = get_winner_ids()
    chosen_game = get_current_chosen_game()
    mvp = get_mvp()  # mvp as str e.g. <@1234567890>

    # Default value
    new_champion_id = None

    # Extract MVP ID if present
    if mvp:
        match = re.search(r"\d+", mvp)  # MVP could be a mention like <@1234567890>
        if match:
            new_champion_id = int(match.group(0))

    # Process all completed matches for detailed stats
    try:
        matches = tournament.get("matches", [])
        teams = tournament.get("teams", {})
        completed_matches = [m for m in matches if m.get("status") == "completed"]

        logger.info(f"[STATS] Processing {len(completed_matches)} completed matches for stats tracking")

        for match in completed_matches:
            winner_team = match.get("winner")
            team1 = match.get("team1")
            team2 = match.get("team2")

            if not winner_team or not team1 or not team2:
                continue

            loser_team = team2 if winner_team == team1 else team1

            winner_team_data = teams.get(winner_team, {})
            loser_team_data = teams.get(loser_team, {})

            winner_members = winner_team_data.get("members", [])
            loser_members = loser_team_data.get("members", [])

            # Extract user IDs (safe regex execution)
            winner_ids_match = []
            for m in winner_members:
                match = re.search(r"\d+", m)
                if match:
                    winner_ids_match.append(match.group(0))

            loser_ids_match = []
            for m in loser_members:
                match = re.search(r"\d+", m)
                if match:
                    loser_ids_match.append(match.group(0))

            if winner_ids_match and loser_ids_match and chosen_game != "Unknown":
                record_match_result(
                    winner_ids=winner_ids_match,
                    loser_ids=loser_ids_match,
                    game=chosen_game,
                    winner_mentions=winner_members,
                    loser_mentions=loser_members
                )

        logger.info(f"[STATS] Match history stats updated for {len(completed_matches)} matches")
    except Exception as e:
        logger.error(f"[STATS] Error processing match stats: {e}", exc_info=True)

    # Update tournament participation for all players
    try:
        all_participant_ids = []
        for team_data in tournament.get("teams", {}).values():
            members = team_data.get("members", [])
            for member in members:
                match = re.search(r"\d+", member)
                if match:
                    all_participant_ids.append(match.group(0))

        if all_participant_ids and chosen_game != "Unknown":
            update_tournament_participation(all_participant_ids, chosen_game)
            logger.info(f"[STATS] Tournament participation updated for {len(all_participant_ids)} players")
    except Exception as e:
        logger.error(f"[STATS] Error updating tournament participation: {e}", exc_info=True)

    if winner_ids:
        update_tournament_wins(winner_ids)
        logger.info(f"[TOURNAMENT] Winners saved: {winner_ids} for game: {chosen_game}")
    else:
        logger.warning("[TOURNAMENT] No winners found.")

    update_tournament_history(
        winner_ids=winner_ids,
        chosen_game=chosen_game or "Unknown",
        mvp_name=mvp or "No MVP",
    )

    reset_tournament()

    try:
        delete_tournament_file()
        logger.info("[TOURNAMENT] Tournament file deleted.")
    except Exception as e:
        logger.error(f"[TOURNAMENT] Error deleting tournament file: {e}")

    # Send final embed (before reset, so chosen_game is available)
    mvp_message = f"🏆 Tournament MVP: **{mvp}**!" if mvp else "🏆 No MVP determined."
    await send_tournament_end_announcement(channel, mvp_message, winner_ids, chosen_game, new_champion_id)

    # Notify winners about available game keys
    if bot and winner_ids:
        try:
            winning_team_name = get_winner_team(winner_ids)
            if winning_team_name:
                from modules.key_manager import notify_winners_about_keys
                await notify_winners_about_keys(bot, winner_ids, winning_team_name)
        except Exception as e:
            logger.error(f"[TOURNAMENT] Error notifying winners about keys: {e}")

    if mvp:  # If MVP exists
        try:
            from modules.utils import extract_user_id
            guild = channel.guild  # Get guild from channel
            mvp_id = extract_user_id(mvp)  # Extract MVP from mention safely
            if mvp_id:
                await update_champion_role(guild, mvp_id)
            else:
                logger.error(f"[CHAMPION] Could not extract valid user ID from MVP mention: {mvp}")
        except Exception as e:
            logger.error(f"[CHAMPION] Error updating champion role: {e}")

    logger.info("[TOURNAMENT] Tournament completed and system ready for new one.")


async def auto_end_poll(bot: discord.Client, channel: discord.TextChannel, delay_seconds: int):
    """Automatically ends poll after delay."""
    await asyncio.sleep(delay_seconds)
    await poll.end_poll(bot, channel)


async def update_champion_role(guild: discord.Guild, new_champion_id: int, role_name: str = "Champion"):
    """
    Updates the Champion role on the server:
    - Removes the role from all previous holders
    - Grants the role to the new champion
    """
    # Find role
    champion_role = discord.utils.get(guild.roles, name=role_name)
    if not champion_role:
        logger.error(f"[CHAMPION] Role '{role_name}' not found!")
        return

    # Assign new champion
    new_champion = guild.get_member(new_champion_id)
    if not new_champion:
        logger.error(f"[CHAMPION] New champion (User ID {new_champion_id}) not found!")
        return

    # Check: Does the new champion already have the role?
    if champion_role in new_champion.roles:
        logger.info(
            f"[CHAMPION] New champion {new_champion.display_name} already has the role – no changes necessary."
        )
        return

    # Find old champion and remove role
    for member in guild.members:
        if champion_role in member.roles:
            try:
                await member.remove_roles(champion_role, reason="New champion was assigned.")
                logger.info(f"[CHAMPION] Champion role removed from {member.display_name}")
            except Exception as e:
                logger.error(f"[CHAMPION] Error removing champion role from {member.display_name}: {e}")

    # Give role to new champion
    try:
        await new_champion.add_roles(champion_role, reason="Tournament victory MVP.")
        logger.info(f"[CHAMPION] Champion role granted to {new_champion.display_name}")
    except Exception as e:
        logger.error(f"[CHAMPION] Error granting champion role to {new_champion.display_name}: {e}")


# ---------------------------------------
# ⏳ Background Tasks
# ---------------------------------------


async def execute_registration_close_procedure(channel: discord.TextChannel):
    """
    Shared procedure for closing registration and starting matchmaking.
    Can be called by both automatic timer and manual admin command.
    """
    tournament = load_tournament_data()

    if not tournament.get("running", False):
        await channel.send(get_message("ERRORS", "no_tournament_running"))
        return

    # Close registration if still open
    if not tournament.get("registration_open", False):
        logger.warning("[CLOSE] Registration was already closed, but continuing with match planning.")
    else:
        tournament["registration_open"] = False
        save_tournament_data(tournament)
        await send_registration_closed(channel)
        logger.info("[TOURNAMENT] Registration closed.")

    try:
        # Step 1: Clean up orphaned teams (modifies tournament data)
        await cleanup_orphan_teams(channel)

        # Step 2: Automatically match solo players (modifies tournament data)
        auto_match_solo()

        # Step 3: Reload after modifications, create schedule
        tournament = load_tournament_data()
        create_round_robin_schedule(tournament)

        # Step 4: Auto-calculate optimal tournament duration
        num_teams = len(tournament.get("teams", {}))
        if num_teams > 0:
            registration_end_str = tournament.get("registration_end")
            if registration_end_str:
                registration_end = datetime.fromisoformat(registration_end_str)
                # Ensure timezone awareness
                tz = ZoneInfo(CONFIG.bot.timezone)
                if registration_end.tzinfo is None:
                    registration_end = registration_end.replace(tzinfo=tz)

                # Calculate and update tournament end
                optimal_end = calculate_optimal_tournament_duration(num_teams, registration_end)
                tournament["tournament_end"] = optimal_end.isoformat()
                save_tournament_data(tournament)
                logger.info(f"[TOURNAMENT] Duration auto-set to {optimal_end.strftime('%Y-%m-%d')}")

        # Step 5: Clear solo list (already processed by auto_match_solo)
        tournament["solo"] = []
        save_tournament_data(tournament)

        # Step 6: Generate slots and assign matches
        await generate_and_assign_slots()

        # Step 7: Check for availability conflicts and resolve them
        from modules.availability_conflict_resolver import ConflictResolutionCoordinator

        resolver = ConflictResolutionCoordinator(channel)
        has_conflicts = await resolver.detect_and_resolve_conflicts()

        if has_conflicts:
            # Conflicts detected - resolution is in progress
            # Schedule will be published after all conflicts are resolved
            logger.info(
                "[REGISTRATION] Availability conflicts detected. "
                "Waiting for resolution before publishing schedule."
            )

            # Load locale message
            from modules.embeds import load_embed_template
            template = load_embed_template("availability_conflict", CONFIG.bot.language)
            messages = template.get("MESSAGES", {})
            msg = messages.get(
                "schedule_pending",
                "⏸️ **Tournament schedule pending**\nWaiting for availability conflicts to be resolved.\n"
                "The schedule will be published automatically once all teams have responded."
            )
            await channel.send(msg)
        else:
            # No conflicts - publish schedule immediately
            tournament = load_tournament_data()
            matches = tournament.get("matches", [])

            description_text = generate_schedule_overview(matches)
            await send_match_schedule_for_channel(channel, description_text)

            logger.info("[REGISTRATION] Registration close procedure completed successfully")

    except Exception as e:
        logger.error(f"[REGISTRATION] Error during close procedure: {e}", exc_info=True)
        await channel.send(get_message("ERRORS", "match_planning_error", error=e))
        raise


async def close_registration_after_delay(delay_seconds: int, channel: discord.TextChannel):
    """
    Closes registration after a delay automatically
    and starts automatic matchmaking & cleanup.

    Thread-safe implementation using lock to prevent double execution.
    """
    global _registration_closed, _registration_lock

    # CRITICAL: Acquire lock BEFORE sleeping to prevent race conditions
    async with _registration_lock:
        if _registration_closed:
            logger.warning("[REGISTRATION] Process already completed – double prevention active.")
            return

        # Mark as in-progress immediately (still holding lock)
        _registration_closed = True
        logger.info(f"[REGISTRATION] Will auto-close in {delay_seconds} seconds")

    # Now we can safely sleep - we've marked ourselves as in-progress
    await asyncio.sleep(delay_seconds)

    # Execute the shared close procedure
    await execute_registration_close_procedure(channel)


async def close_tournament_after_delay(delay_seconds: int, channel: discord.TextChannel):
    """Closes tournament after delay."""
    await asyncio.sleep(delay_seconds)

    await end_tournament_procedure(channel)


async def setup(bot):
    """
    Setup function for tournament module.

    Note: This module provides utility functions and background tasks,
    but does not register any cogs or commands. Tournament-related commands
    are registered in other modules (admin_tools, players, etc.).
    """
    logger.info("[SYSTEM] ✅ Tournament module loaded (utility functions only)")
