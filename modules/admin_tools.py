# modules/admin_tools.py

import os
import zipfile
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
import asyncio


import discord
from discord import Interaction, app_commands
from discord.ext import commands

# Local modules
from modules import poll
from modules.archive import archive_current_tournament
from modules.config import CONFIG
from modules.dataStorage import (
    load_global_data,
    load_tournament_data,
    add_game,
    remove_game,
    save_global_data,
    save_tournament_data,
    load_games
)
from modules.embeds import send_match_schedule, load_embed_template, build_embed_from_template
from modules.logger import logger
from modules.task_manager import add_task
from modules.matchmaker import (
    auto_match_solo,
    cleanup_orphan_teams,
    create_round_robin_schedule,
    generate_and_assign_slots,
    generate_schedule_overview,
)
from modules.modals import (
    AddGameModal,
    TestModal,
    StartTournamentModal
)

from modules.poll import end_poll
from modules.reschedule import pending_reschedules, _reschedule_lock
from modules.stats_tracker import record_match_result
from modules.tournament import end_tournament_procedure, auto_end_poll, execute_registration_close_procedure
from modules.utils import (
    autocomplete_teams,
    games_autocomplete,
    has_permission,
    smart_send,
)


# ----------------------------------------
# Admin Helper Functions
# ----------------------------------------
async def pending_match_autocomplete(interaction: Interaction, current: str):
    """
    Autocomplete for pending reschedule matches (IDs only).
    """
    choices = []

    # If no pending reschedules exist ➝ suggest nothing
    if not pending_reschedules:
        return []

    for match_id in pending_reschedules:
        if current in str(match_id):  # Filters by entered number
            choices.append(app_commands.Choice(name=f"Match {match_id}", value=match_id))

    return choices[:25]  # Return maximum 25 entries

async def handle_start_tournament_modal(
    interaction: Interaction,
    poll_duration: int,
    registration_duration: int,
    team_size: int,
):
    logger.debug("[MODAL] handle_start_tournament_modal() was called")

    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.followup.send("🚫 No permission.", ephemeral=True)
        return

    # Reset registration closed flag for new tournament
    from modules.tournament import _registration_lock
    import modules.tournament as tournament_module
    async with _registration_lock:
        tournament_module._registration_closed = False
        logger.debug("[TOURNAMENT] Registration flag reset for new tournament")

    try:
        tournament = load_tournament_data()
        if tournament.get("running", False):
            await interaction.followup.send(
                "🚫 A tournament is already running! Please end it first with `/admin end_tournament`.",
                ephemeral=True,
            )
            return

        now = datetime.now(ZoneInfo(CONFIG.bot.timezone))
        registration_end = now + timedelta(hours=registration_duration)
        # Set generous default duration (12 weeks) - will be automatically recalculated
        # after registration closes based on actual number of teams
        tournament_end = registration_end + timedelta(weeks=12)

        tournament = {
            "registration_open": False,
            "running": True,
            "teams": {},
            "solo": [],
            "registration_end": registration_end.astimezone(ZoneInfo("UTC")).isoformat(),
            "tournament_end": tournament_end.isoformat(),
            "matches": [],
            "team_size": team_size,
        }
        save_tournament_data(tournament)

        logger.info(
            f"[TOURNAMENT] Tournament started: "
            f"Poll {poll_duration}h, Registration {registration_duration}h, Team size {team_size} "
            f"(Duration will be auto-calculated after registration)"
        )

        # Send embed
        template = load_embed_template("tournament_start").get("TOURNAMENT_ANNOUNCEMENT")
        embed = build_embed_from_template(template) if template else Embed(
            title="🎮 Tournament started!",
            description=f"The game poll is now running for {poll_duration} hours.",
            color=discord.Color.green(),
        )
        await interaction.followup.send(embed=embed, ephemeral=False)

        # Load games
        poll_options = load_games()
        visible_games = {
            k: v for k, v in poll_options.items() if v.get("visible_in_poll", True)
        }
        if not visible_games:
            await interaction.followup.send("⚠️ No games available for the poll.", ephemeral=True)
            logger.warning("[MODAL] No games with visible_in_poll=True found.")
            return

        logger.info(f"[MODAL] {len(visible_games)} games loaded: {list(visible_games.keys())}")

        # Start poll
        await poll.start_poll(
            interaction.channel,
            visible_games,
            registration_hours=registration_duration,
            poll_duration_hours=poll_duration,
        )

        # Set timer
        duration_seconds = poll_duration * 3600
        add_task(
            "auto_end_poll",
            asyncio.create_task(auto_end_poll(interaction.client, interaction.channel, duration_seconds)),
        )

    except Exception as e:
        logger.error(f"[MODAL] Error starting tournament: {e}")
        await interaction.followup.send(
            f"❌ Error starting tournament: {e}", ephemeral=True
        )



# ----------------------------------------
# Slash Functions
# ----------------------------------------
class AdminGroup(app_commands.Group):
    def __init__(self):
        super().__init__(
            name="admin",
            description="Admin and moderator commands",
            default_permissions=discord.Permissions(administrator=True)
        )

    # --------- ADMIN COMMANDS ----------
    @app_commands.command(
        name="add_win",
        description="Admin command: Manually grants a tournament win to a player.",
    )
    @app_commands.describe(user="The player who should receive the win.")
    async def add_win(self, interaction: Interaction, user: discord.Member):
        from modules.stats_tracker import load_player_stats, save_player_stats, initialize_player_stats

        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 You don't have permission for this command.", ephemeral=True)
            return

        user_id = str(user.id)

        # Load or initialize player stats
        stats = load_player_stats(user_id)
        if stats is None:
            stats = initialize_player_stats(user_id, user.mention, user.display_name)

        # Increment tournament wins
        stats["wins"] += 1

        # Save updated stats
        save_player_stats(user_id, stats)

        await interaction.response.send_message(
            f"✅ {user.mention} was credited with an additional win.",
            ephemeral=True,
        )
        logger.info(f"[ADMIN] {user.display_name} was manually added a win.")


    @app_commands.command(
        name="start_tournament",
        description="Starts a new tournament via input form.",
    )
    async def start_tournament(self, interaction: Interaction):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 No permission.", ephemeral=True)
            return

        await interaction.response.send_modal(StartTournamentModal(interaction))


    @app_commands.command(name="end_tournament", description="Admin command: Ends the current tournament.")
    async def end_tournament(self, interaction: Interaction):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 You don't have permission for this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        await interaction.followup.send(
            "🏁 Tournament end is being prepared... this may take a few seconds!",
            ephemeral=True,
        )

        await end_tournament_procedure(interaction.channel, manual_trigger=True)


    @app_commands.command(name="manage_game", description="Add or remove a game.")
    @app_commands.describe(action="add or remove", game="Game ID or name")
    @app_commands.choices(action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Remove", value="remove")
    ])
    @app_commands.autocomplete(game=games_autocomplete)
    async def manage_game(self, interaction: Interaction, action: str, game: str):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 No permission.", ephemeral=True)
            return

        if action == "add":
            await interaction.response.send_modal(AddGameModal())
        elif action == "remove":
            try:
                remove_game(game)
                await interaction.response.send_message(f"🗑 Game `{game}` was removed.", ephemeral=True)
            except ValueError as e:
                await interaction.response.send_message(f"⚠️ {str(e)}", ephemeral=True)



    @app_commands.command(name="report_match", description="Report a match result by match ID.")
    @app_commands.describe(
        match_id="Match ID to report result for",
        winner="The winning team",
    )
    @app_commands.autocomplete(winner=autocomplete_teams)
    async def report_match(self, interaction: Interaction, match_id: int, winner: str):
        """
        Allows admins to report a match result for a tournament game.
        Sets the match status to completed and records the winner.
        """
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 You don't have permission for this command.", ephemeral=True)
            return

        tournament = load_tournament_data()
        matches = tournament.get("matches", [])

        # Find the match
        match = next((m for m in matches if m.get("match_id") == match_id), None)

        if not match:
            await interaction.response.send_message(
                f"🚫 Match with ID {match_id} not found.",
                ephemeral=True
            )
            return

        team1 = match.get("team1")
        team2 = match.get("team2")

        # Validate winner
        if winner not in [team1, team2]:
            await interaction.response.send_message(
                f"🚫 Winner must be either **{team1}** or **{team2}**.",
                ephemeral=True
            )
            return

        # Check if match is already completed
        if match.get("status") == "completed":
            await interaction.response.send_message(
                f"⚠️ Match {match_id} is already marked as completed.\n"
                f"Current winner: **{match.get('winner', 'Unknown')}**\n"
                f"Do you want to overwrite?",
                ephemeral=True
            )
            # For now, we'll allow overwriting
            logger.warning(f"[ADMIN] Overwriting completed match {match_id} result")

        # Update match
        match["status"] = "completed"
        match["winner"] = winner
        match["reported_by"] = interaction.user.mention
        match["reported_at"] = datetime.now(tz=ZoneInfo(CONFIG.bot.timezone)).isoformat()

        save_tournament_data(tournament)

        # Track player stats
        loser = team2 if winner == team1 else team1
        try:
            teams = tournament.get("teams", {})
            winner_team_data = teams.get(winner, {})
            loser_team_data = teams.get(loser, {})

            winner_members = winner_team_data.get("members", [])
            loser_members = loser_team_data.get("members", [])

            # Extract user IDs from mentions (safe regex execution)
            import re
            winner_ids = []
            for m in winner_members:
                match = re.search(r"\d+", m)
                if match:
                    winner_ids.append(match.group(0))

            loser_ids = []
            for m in loser_members:
                match = re.search(r"\d+", m)
                if match:
                    loser_ids.append(match.group(0))

            # Get game name
            game = tournament.get("poll_results", {}).get("chosen_game", "Unknown")

            # Record match result in stats
            if winner_ids and loser_ids and game != "Unknown":
                record_match_result(
                    winner_ids=winner_ids,
                    loser_ids=loser_ids,
                    game=game,
                    winner_mentions=winner_members,
                    loser_mentions=loser_members
                )
                logger.info(f"[STATS] Match stats recorded for match {match_id}")
        except Exception as e:
            logger.error(f"[STATS] Error recording match stats: {e}")
            # Don't fail the command if stats tracking fails

        await interaction.response.send_message(
            f"✅ Match {match_id} result saved:\n\n"
            f"**{team1}** vs **{team2}**\n"
            f"🏆 Winner: **{winner}**\n"
            f"❌ Loser: **{loser}**",
            ephemeral=False
        )

        logger.info(f"[MATCH REPORT] Match {match_id}: {team1} vs {team2} – Winner: {winner}")


    @app_commands.command(name="reload", description="Synchronizes all slash commands.")
    async def reload_commands(self, interaction: Interaction):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 You don't have permission for this command.", ephemeral=True)
            return

        await interaction.response.send_message("🔄 Synchronizing slash commands...", ephemeral=True)

        try:
            synced = await interaction.client.tree.sync()
            await interaction.edit_original_response(content=f"✅ {len(synced)} slash commands were reloaded.")
            logger.info(f"[RELOAD] {len(synced)} slash commands reloaded by {interaction.user.display_name}")
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ Error reloading: {e}")
            logger.error(f"[RELOAD ERROR] {e}")

    @app_commands.command(
        name="close_registration",
        description="Closes registration and starts match generation.",
    )
    async def close_registration(self, interaction: Interaction):
        """
        Manually closes tournament registration and initiates matchmaking.
        Uses shared procedure from tournament.py to ensure consistency.
        """
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 You don't have permission for this command.", ephemeral=True)
            return

        try:
            await interaction.response.defer(thinking=True, ephemeral=True)
        except Exception as e:
            logger.warning(f"[CLOSE_REG] Could not defer: {e}")

        tournament = load_tournament_data()

        if not tournament.get("running", False):
            await interaction.followup.send("🚫 No tournament active.", ephemeral=True)
            return

        if not tournament.get("registration_open", True):
            logger.warning("[CLOSE_REG] Registration was already closed - executing procedure again.")

        await interaction.followup.send("🔒 **Closing registration and starting match planning...**", ephemeral=True)

        # Use shared procedure from tournament.py
        await execute_registration_close_procedure(interaction.channel)

        logger.info("[CLOSE_REG] Registration manually closed and matches planned.")


    @app_commands.command(name="archive_tournament", description="Archives the current tournament.")
    async def archive_tournament(self, interaction: Interaction):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 You don't have permission for this command.", ephemeral=True)
            return

        file_path = archive_current_tournament()
        await interaction.response.send_message(f"✅ Tournament archived: `{file_path}`", ephemeral=True)

        logger.info(f"[ARCHIVE] Tournament successfully archived at {file_path}")

    @app_commands.command(
        name="reset_reschedule",
        description="Manually resets a pending reschedule request.",
    )
    @app_commands.describe(match_id="Select match ID")
    @app_commands.autocomplete(match_id=pending_match_autocomplete)
    async def reset_reschedule(self, interaction: Interaction, match_id: int):
        global pending_reschedules
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 You don't have permission for this command.", ephemeral=True)
            return

        async with _reschedule_lock:
            if match_id in pending_reschedules:
                pending_reschedules.discard(match_id)
                await interaction.response.send_message(
                    f"✅ Reschedule request for match {match_id} was reset.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"⚠️ No pending request for match {match_id} found.", ephemeral=True
                )

    @app_commands.command(
        name="end_poll",
        description="Ends the current game poll and starts registration.",
    )
    async def end_poll_command(self, interaction: discord.Interaction):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 You don't have permission for this.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            await end_poll(interaction.client, interaction.channel)
            logger.info("[END_POLL] end_poll() successfully completed.")
            await interaction.edit_original_response(content="✅ Poll has been ended!")
        except Exception as e:
            logger.error(f"[END_POLL] Error ending poll: {e}")
            await interaction.edit_original_response(content=f"❌ Error ending poll: {e}")

    @app_commands.command(
        name="export_data",
        description="Exports all current tournament data as ZIP file (via DM).",
    )
    async def export_data(self, interaction: Interaction):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 No permission.", ephemeral=True)
            return

        export_dir = "exports"
        os.makedirs(export_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_name = f"tournament_export_{timestamp}.zip"
        zip_path = os.path.join(export_dir, zip_name)

        with zipfile.ZipFile(zip_path, "w") as zipf:
            for f in ["data/data.json", "data/tournament.json"]:
                if os.path.exists(f):
                    zipf.write(f)

        file = discord.File(zip_path)

        # ✅ Try to send via DM
        try:
            await interaction.user.send(content="📦 Here is your tournament export:", file=file)
            await interaction.response.send_message("✅ ZIP file was sent to you via DM.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "⚠️ Could not send you a DM. Make sure DMs from the server are allowed.",
                ephemeral=True,
            )


# ----------------------------------------
# Hook for Cog
# ----------------------------------------
class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.tree.add_command(AdminGroup())


# Extension setup:
async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
