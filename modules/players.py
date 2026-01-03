from typing import Optional

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
        Unregisters the user from the tournament.
        """

        tournament = load_tournament_data()

        if not tournament.get("running", False):
            await interaction.response.send_message("No tournament is currently running.", ephemeral=True)
            return

        user_mention = interaction.user.mention
        user_name = interaction.user.display_name
        found_team = None
        found_team_entry = None

        for team, team_entry in tournament.get("teams", {}).items():
            if user_mention in team_entry.get("members", []):
                found_team = team
                found_team_entry = team_entry
                break

        if found_team:
            if tournament.get("registration_open", False):
                # DURING REGISTRATION: Dissolve team, move partner to solo queue
                other_members = [m for m in found_team_entry.get("members", []) if m != user_mention]
                del tournament["teams"][found_team]
                if other_members:
                    availability = found_team_entry.get("availability", "")
                    tournament.setdefault("solo", []).append(
                        {"player": other_members[0], "availability": availability}
                    )

                    # Resolve names
                    try:
                        other_id = int(other_members[0].strip("<@!>"))
                        other_member = interaction.guild.get_member(other_id)
                        other_name = other_member.display_name if other_member else other_members[0]
                    except (ValueError, AttributeError):
                        other_name = other_members[0]
                        logger.error(f"[LEAVE] Failed to parse member ID: {other_members[0]}")

                    logger.info(f"[LEAVE] {other_name} was transferred from team {found_team} to solo list.")
                save_tournament_data(tournament)
                logger.info(f"[LEAVE] {user_name} left team {found_team}. Team was dissolved.")
                await interaction.response.send_message(
                    f"✅ You have been successfully unregistered from team {found_team}.",
                    ephemeral=True,
                )
                return
            else:
                # AFTER REGISTRATION: Mark team as withdrawn, forfeit all open matches
                from datetime import datetime

                # Mark team as withdrawn (keep in system for match integrity)
                tournament["teams"][found_team]["status"] = "withdrawn"
                tournament["teams"][found_team]["withdrawn_by"] = user_mention
                tournament["teams"][found_team]["withdrawn_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

                # Forfeit only OPEN matches involving this team
                forfeited_matches = 0
                for match in tournament.get("matches", []):
                    if found_team in (match.get("team1"), match.get("team2")):
                        # Only forfeit open matches - preserve completed/already forfeited matches
                        if match.get("status") == "open":
                            match["status"] = "forfeit"
                            # Opponent gets automatic win
                            opponent = match["team2"] if match["team1"] == found_team else match["team1"]

                            # Check if opponent team is also withdrawn
                            opponent_status = tournament.get("teams", {}).get(opponent, {}).get("status")
                            if opponent_status == "withdrawn":
                                # Both teams withdrawn - no winner
                                match["winner"] = "None (both teams withdrawn)"
                            else:
                                match["winner"] = opponent

                            match["forfeit_by"] = found_team
                            forfeited_matches += 1

                # Notify partner (if team has 2+ members)
                other_members = [m for m in found_team_entry.get("members", []) if m != user_mention]
                if other_members:
                    # Send DM or mention in channel about team withdrawal
                    try:
                        partner_mention = other_members[0]
                        await interaction.channel.send(
                            f"⚠️ {partner_mention}: Your teammate has left the tournament. "
                            f"Team **{found_team}** has been withdrawn and all matches forfeited."
                        )
                    except Exception as e:
                        logger.warning(f"[LEAVE] Failed to notify partner: {e}")

                save_tournament_data(tournament)
                logger.warning(f"[LEAVE] {user_name} left team {found_team} after registration close. "
                              f"Team marked as withdrawn, {forfeited_matches} matches forfeited.")
                await interaction.response.send_message(
                    f"✅ You have left team **{found_team}**.\n"
                    f"⚠️ The team has been withdrawn and all {forfeited_matches} matches forfeited.",
                    ephemeral=True
                )
                return

        for entry in tournament.get("solo", []):
            if entry.get("player") == user_mention:
                tournament["solo"].remove(entry)
                save_tournament_data(tournament)
                logger.info(f"[LEAVE] Solo player {user_name} was successfully unregistered.")
                await interaction.response.send_message(
                    "✅ You have been successfully removed from the solo list.",
                    ephemeral=True,
                )
                return

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
