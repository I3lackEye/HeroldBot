"""
Leave Confirmation View

Provides a confirmation dialog before a player leaves the tournament.
Shows different consequences based on tournament state.
"""

from discord import ui, ButtonStyle, Interaction, Embed, Color
from datetime import datetime

from modules.dataStorage import load_tournament_data, save_tournament_data
from modules.logger import logger


class LeaveConfirmationView(ui.View):
    """
    Confirmation view for leaving the tournament.
    Displays consequences and requires explicit confirmation.
    """

    def __init__(self, user_mention: str, user_name: str, team_name: str, team_data: dict, is_during_registration: bool):
        super().__init__(timeout=60)  # 1 minute to decide
        self.user_mention = user_mention
        self.user_name = user_name
        self.team_name = team_name
        self.team_data = team_data
        self.is_during_registration = is_during_registration
        self.confirmed = False
        self.message = None

    @ui.button(label="✅ Yes, Leave Tournament", style=ButtonStyle.danger)
    async def confirm_leave(self, interaction: Interaction, button: ui.Button):
        """Confirm leaving the tournament."""
        if interaction.user.mention != self.user_mention:
            await interaction.response.send_message(
                "🚫 Only the person who initiated this can confirm.",
                ephemeral=True
            )
            return

        await interaction.response.defer()
        self.confirmed = True

        # Execute the leave logic
        await self._execute_leave(interaction)
        self.stop()

    @ui.button(label="❌ Cancel", style=ButtonStyle.secondary)
    async def cancel_leave(self, interaction: Interaction, button: ui.Button):
        """Cancel the leave operation."""
        if interaction.user.mention != self.user_mention:
            await interaction.response.send_message(
                "🚫 Only the person who initiated this can cancel.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "✅ Cancelled. You remain in the tournament.",
            ephemeral=True
        )

        if self.message:
            await self.message.edit(
                content="❌ Leave operation cancelled.",
                embed=None,
                view=None
            )

        self.stop()

    async def _execute_leave(self, interaction: Interaction):
        """Execute the actual leave logic based on tournament state."""
        tournament = load_tournament_data()

        if self.is_during_registration:
            # DURING REGISTRATION: Dissolve team, move partner to solo queue
            await self._leave_during_registration(interaction, tournament)
        else:
            # AFTER REGISTRATION: Mark team as withdrawn, forfeit matches
            await self._leave_after_registration(interaction, tournament)

    async def _leave_during_registration(self, interaction: Interaction, tournament: dict):
        """Handle leaving during registration phase."""
        other_members = [m for m in self.team_data.get("members", []) if m != self.user_mention]

        # Delete team
        del tournament["teams"][self.team_name]

        # Move partner to solo queue if exists
        if other_members:
            availability = self.team_data.get("availability", {})
            tournament.setdefault("solo", []).append({
                "player": other_members[0],
                "availability": availability,
                "unavailable_dates": self.team_data.get("unavailable_dates", [])
            })

            # Resolve partner name for logging
            try:
                other_id = int(other_members[0].strip("<@!>"))
                other_member = interaction.guild.get_member(other_id)
                other_name = other_member.display_name if other_member else other_members[0]
            except (ValueError, AttributeError):
                other_name = other_members[0]
                logger.error(f"[LEAVE] Failed to parse member ID: {other_members[0]}")

            logger.info(f"[LEAVE] {other_name} was transferred from team {self.team_name} to solo list.")

        save_tournament_data(tournament)
        logger.info(f"[LEAVE] {self.user_name} left team {self.team_name}. Team was dissolved.")

        # Send confirmation
        if self.message:
            await self.message.edit(
                content=f"✅ You have successfully left team **{self.team_name}**.",
                embed=None,
                view=None
            )

    async def _leave_after_registration(self, interaction: Interaction, tournament: dict):
        """Handle leaving after registration has closed."""
        # Mark team as withdrawn
        tournament["teams"][self.team_name]["status"] = "withdrawn"
        tournament["teams"][self.team_name]["withdrawn_by"] = self.user_mention
        tournament["teams"][self.team_name]["withdrawn_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        # Forfeit only OPEN matches
        forfeited_matches = 0
        for match in tournament.get("matches", []):
            if self.team_name in (match.get("team1"), match.get("team2")):
                if match.get("status") == "open":
                    match["status"] = "forfeit"
                    opponent = match["team2"] if match["team1"] == self.team_name else match["team1"]

                    # Check if opponent is also withdrawn
                    opponent_status = tournament.get("teams", {}).get(opponent, {}).get("status")
                    if opponent_status == "withdrawn":
                        match["winner"] = "None (both teams withdrawn)"
                    else:
                        match["winner"] = opponent

                    match["forfeit_by"] = self.team_name
                    forfeited_matches += 1

        save_tournament_data(tournament)
        logger.warning(
            f"[LEAVE] {self.user_name} left team {self.team_name} after registration close. "
            f"Team marked as withdrawn, {forfeited_matches} matches forfeited."
        )

        # Notify partner
        other_members = [m for m in self.team_data.get("members", []) if m != self.user_mention]
        if other_members:
            try:
                partner_mention = other_members[0]
                await interaction.channel.send(
                    f"⚠️ {partner_mention}: Your teammate has left the tournament. "
                    f"Team **{self.team_name}** has been withdrawn and all matches forfeited."
                )
            except Exception as e:
                logger.warning(f"[LEAVE] Failed to notify partner: {e}")

        # Send confirmation
        if self.message:
            await self.message.edit(
                content=(
                    f"✅ You have left team **{self.team_name}**.\n"
                    f"⚠️ The team has been withdrawn and **{forfeited_matches} match(es)** forfeited."
                ),
                embed=None,
                view=None
            )

    async def on_timeout(self):
        """Handle timeout - cancel the operation."""
        logger.info(f"[LEAVE] Timeout for {self.user_name} leave confirmation - cancelled.")

        if self.message:
            await self.message.edit(
                content="⌛ Leave confirmation timed out. You remain in the tournament.",
                embed=None,
                view=None
            )


def create_leave_confirmation_embed(
    team_name: str,
    team_data: dict,
    user_mention: str,
    is_during_registration: bool
) -> Embed:
    """
    Create an embed showing the consequences of leaving.

    :param team_name: Name of the team
    :param team_data: Team data dict
    :param user_mention: User mention string
    :param is_during_registration: Whether registration is still open
    :return: Discord Embed
    """
    other_members = [m for m in team_data.get("members", []) if m != user_mention]
    has_partner = len(other_members) > 0

    if is_during_registration:
        # During registration - lighter consequences
        embed = Embed(
            title="⚠️ Leave Tournament - Confirmation",
            description=(
                f"You are about to leave team **{team_name}**.\n\n"
                f"**What will happen:**"
            ),
            color=Color.orange()
        )

        consequences = []
        consequences.append("🔹 Your team will be **dissolved**")

        if has_partner:
            consequences.append(f"🔹 Your partner ({other_members[0]}) will be moved to the **solo queue**")
            consequences.append("🔹 They may be matched with another solo player")

        consequences.append("🔹 You will be **completely removed** from the tournament")
        consequences.append("🔹 You can **re-register** at any time before registration closes")

        embed.add_field(
            name="📋 Consequences",
            value="\n".join(consequences),
            inline=False
        )

        embed.add_field(
            name="✅ Safe to Leave",
            value="Registration is still open, so there are no penalties for leaving now.",
            inline=False
        )

    else:
        # After registration - serious consequences
        embed = Embed(
            title="🚨 Leave Tournament - WARNING",
            description=(
                f"You are about to leave team **{team_name}**.\n\n"
                f"**⚠️ SERIOUS CONSEQUENCES - READ CAREFULLY:**"
            ),
            color=Color.red()
        )

        tournament = load_tournament_data()
        matches = tournament.get("matches", [])

        # Count open matches
        open_match_count = sum(
            1 for m in matches
            if team_name in (m.get("team1"), m.get("team2")) and m.get("status") == "open"
        )

        consequences = []
        consequences.append("🔹 Your team will be marked as **WITHDRAWN**")
        consequences.append(f"🔹 **{open_match_count} match(es)** will be **forfeited**")
        consequences.append("🔹 All forfeited matches count as **automatic losses**")
        consequences.append("🔹 Your opponents will receive **automatic wins**")

        if has_partner:
            consequences.append(f"🔹 Your partner ({other_members[0]}) will also be **eliminated**")

        consequences.append("🔹 This action **CANNOT BE UNDONE**")
        consequences.append("🔹 You **CANNOT re-join** this tournament")

        embed.add_field(
            name="⚠️ Consequences",
            value="\n".join(consequences),
            inline=False
        )

        if has_partner:
            embed.add_field(
                name="👥 Impact on Partner",
                value=(
                    f"Your partner will be notified and the entire team will be withdrawn.\n"
                    f"Both of you will be removed from the tournament."
                ),
                inline=False
            )

        embed.add_field(
            name="🛑 Are you absolutely sure?",
            value=(
                "Only proceed if you cannot continue playing in this tournament.\n"
                "Consider discussing with your partner first if applicable."
            ),
            inline=False
        )

    embed.set_footer(text="⏰ You have 60 seconds to decide.")

    return embed
