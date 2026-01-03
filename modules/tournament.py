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
    update_player_stats,
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
    update_all_participants,
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
        await channel.send("⚠️ Not all matches are completed yet. Tournament remains open.")
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

    updated_count = await update_all_participants()
    logger.info(f"[TOURNAMENT] {updated_count} participant statistics updated.")

    if winner_ids and chosen_game != "Unknown":
        update_player_stats(winner_ids, chosen_game)
        logger.info(f"[TOURNAMENT] Winners saved: {winner_ids} for game: {chosen_game}")
    else:
        logger.warning("[TOURNAMENT] No winners or game name found.")

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

    if mvp:  # If MVP exists
        try:
            guild = channel.guild  # Get guild from channel
            mvp_id = int(mvp.strip("<@!>"))  # Extract MVP from mention
            await update_champion_role(guild, mvp_id)
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

    # Load tournament data once
    tournament = load_tournament_data()

    if not tournament.get("running", False):
        await channel.send("⚠️ No tournament is running – registration will not be closed.")
        return

    # Close registration if still open
    if not tournament.get("registration_open", False):
        logger.warning("[CLOSE] Registration was already closed, but continuing with match planning.")
    else:
        tournament["registration_open"] = False
        save_tournament_data(tournament)
        await send_registration_closed(channel)
        logger.info("[TOURNAMENT] Registration automatically closed.")

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
            await channel.send(
                "⏸️ **Tournament schedule pending**\n"
                "Waiting for availability conflicts to be resolved.\n"
                "The schedule will be published automatically once all teams have responded."
            )
        else:
            # No conflicts - publish schedule immediately
            tournament = load_tournament_data()
            matches = tournament.get("matches", [])

            description_text = generate_schedule_overview(matches)
            await send_match_schedule_for_channel(channel, description_text)

            logger.info("[REGISTRATION] Registration close procedure completed successfully")

    except Exception as e:
        logger.error(f"[REGISTRATION] Error during close procedure: {e}", exc_info=True)
        await channel.send(f"⚠️ An error occurred during match planning: {e}")
        raise


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
    logger.info("[TOURNAMENT] Tournament module loaded (utility functions only)")
