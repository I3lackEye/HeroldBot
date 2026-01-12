from typing import Optional

from modules.embeds import get_message
import discord
from discord import Embed, Interaction, Member, app_commands
from discord.ext import commands
from discord.ui import Modal, TextInput

# Local modules
from modules.dataStorage import load_tournament_data, save_tournament_data
from modules.embeds import (
    send_registration_confirmation,
    send_wrong_channel,
)
from modules.logger import logger
from modules.modals import TeamFullJoinModal
from modules.reschedule import (
    handle_request_reschedule,
    match_id_autocomplete,
    neuer_zeitpunkt_autocomplete,
)
from modules.utils import (
    generate_team_name,
    has_permission,
    validate_string,
)


# ----------------------------------------
# Slash Commands
# ----------------------------------------
class PlayerGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="player", description="Commands for player registration and availability.")

    @app_commands.command(
        name="request_reschedule",
        description="Request a rescheduling for a match."
    )
    @app_commands.describe(match_id="Match ID you want to reschedule")
    async def request_reschedule(self, interaction: Interaction, match_id: int):
        await handle_request_reschedule(interaction, match_id)

    @app_commands.command(name="leave", description="Unregister from the tournament.")
    async def leave(self, interaction: Interaction):
        """
        Unregisters the user from the tournament with confirmation dialog.
        """
        from modules.leave_confirmation_view import (
            LeaveConfirmationView,
            create_leave_confirmation_embed
        )

        tournament = load_tournament_data()

        if not tournament.get("running", False):
            await interaction.response.send_message("No tournament is currently running.", ephemeral=True)
            return

        user_mention = interaction.user.mention
        user_name = interaction.user.display_name
        found_team = None
        found_team_entry = None

        # Check if user is in a team
        for team, team_entry in tournament.get("teams", {}).items():
            if user_mention in team_entry.get("members", []):
                found_team = team
                found_team_entry = team_entry
                break

        if found_team:
            # User is in a team - show confirmation dialog
            is_during_registration = tournament.get("registration_open", False)

            embed = create_leave_confirmation_embed(
                team_name=found_team,
                team_data=found_team_entry,
                user_mention=user_mention,
                is_during_registration=is_during_registration
            )

            view = LeaveConfirmationView(
                user_mention=user_mention,
                user_name=user_name,
                team_name=found_team,
                team_data=found_team_entry,
                is_during_registration=is_during_registration
            )

            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            view.message = await interaction.original_response()
            return

        # Check if user is in solo queue
        for entry in tournament.get("solo", []):
            if entry.get("player") == user_mention:
                # Solo player - no confirmation needed (low impact)
                tournament["solo"].remove(entry)
                save_tournament_data(tournament)
                logger.info(f"[LEAVE] Solo player {user_name} was successfully unregistered.")
                await interaction.response.send_message(
                    "✅ You have been successfully removed from the solo list.",
                    ephemeral=True,
                )
                return

        # User not found in tournament
        logger.warning(f"[LEAVE] {user_name} wanted to unregister but was not found.")
        await interaction.response.send_message(
            "⚠ You are neither registered in a team nor on the solo list.",
            ephemeral=True,
        )

    @app_commands.command(name="join", description="Register solo or as a team for the tournament")
    async def join(self, interaction: Interaction):
        modal = TeamFullJoinModal()
        await interaction.response.send_modal(modal)


class PlayerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.group = PlayerGroup()
        bot.tree.add_command(self.group)

        self.group.request_reschedule.autocomplete("match_id")(match_id_autocomplete)

async def setup(bot: commands.Bot):
    await bot.add_cog(PlayerCog(bot))
