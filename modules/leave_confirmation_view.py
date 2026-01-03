"""
Leave Confirmation View

Provides a confirmation dialog before a player leaves the tournament.
Shows different consequences based on tournament state.
Uses locale system for internationalization.
"""

from discord import ui, ButtonStyle, Interaction, Embed
from datetime import datetime

from modules.dataStorage import load_tournament_data, save_tournament_data
from modules.logger import logger
from modules.embeds import load_embed_template, build_embed_from_template
from modules.config import CONFIG


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
        self.language = CONFIG.bot.language

        # Load locale messages
        self.template = load_embed_template("leave_confirmation", self.language)
        self.messages = self.template.get("MESSAGES", {})

        # Update button labels from locale
        for item in self.children:
            if isinstance(item, ui.Button):
                if item.custom_id == "confirm_leave":
                    item.label = self.messages.get("button_confirm", "✅ Yes, Leave Tournament")
                elif item.custom_id == "cancel_leave":
                    item.label = self.messages.get("button_cancel", "❌ Cancel")

    @ui.button(label="✅ Yes, Leave Tournament", style=ButtonStyle.danger, custom_id="confirm_leave")
    async def confirm_leave(self, interaction: Interaction, button: ui.Button):
        """Confirm leaving the tournament."""
        if interaction.user.mention != self.user_mention:
            msg = self.messages.get("only_initiator", "🚫 Only the person who initiated this can confirm.")
            await interaction.response.send_message(msg, ephemeral=True)
            return

        await interaction.response.defer()
        self.confirmed = True

        # Execute the leave logic
        await self._execute_leave(interaction)
        self.stop()

    @ui.button(label="❌ Cancel", style=ButtonStyle.secondary, custom_id="cancel_leave")
    async def cancel_leave(self, interaction: Interaction, button: ui.Button):
        """Cancel the leave operation."""
        if interaction.user.mention != self.user_mention:
            msg = self.messages.get("only_initiator_cancel", "🚫 Only the person who initiated this can cancel.")
            await interaction.response.send_message(msg, ephemeral=True)
            return

        msg = self.messages.get("already_cancelled", "✅ Cancelled. You remain in the tournament.")
        await interaction.response.send_message(msg, ephemeral=True)

        if self.message:
            cancelled_msg = self.messages.get("cancelled", "❌ Leave operation cancelled.")
            await self.message.edit(content=cancelled_msg, embed=None, view=None)

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
            msg = self.messages.get("confirm_left", "✅ You have successfully left team **{team}**.")
            msg = msg.replace("PLACEHOLDER_TEAM_NAME", self.team_name)
            await self.message.edit(content=msg, embed=None, view=None)

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
                msg = self.messages.get("partner_notification", "⚠️ {partner}: Your teammate has left the tournament.")
                msg = msg.replace("PLACEHOLDER_PARTNER", partner_mention)
                msg = msg.replace("PLACEHOLDER_TEAM_NAME", self.team_name)
                await interaction.channel.send(msg)
            except Exception as e:
                logger.warning(f"[LEAVE] Failed to notify partner: {e}")

        # Send confirmation
        if self.message:
            msg = self.messages.get("confirm_left_forfeited", "✅ You have left team **{team}**.\n⚠️ {count} match(es) forfeited.")
            msg = msg.replace("PLACEHOLDER_TEAM_NAME", self.team_name)
            msg = msg.replace("PLACEHOLDER_MATCH_COUNT", str(forfeited_matches))
            await self.message.edit(content=msg, embed=None, view=None)

    async def on_timeout(self):
        """Handle timeout - cancel the operation."""
        logger.info(f"[LEAVE] Timeout for {self.user_name} leave confirmation - cancelled.")

        if self.message:
            msg = self.messages.get("timeout", "⌛ Leave confirmation timed out. You remain in the tournament.")
            await self.message.edit(content=msg, embed=None, view=None)


def create_leave_confirmation_embed(
    team_name: str,
    team_data: dict,
    user_mention: str,
    is_during_registration: bool,
    language: str = None
) -> Embed:
    """
    Create an embed showing the consequences of leaving using locale templates.

    :param team_name: Name of the team
    :param team_data: Team data dict
    :param user_mention: User mention string
    :param is_during_registration: Whether registration is still open
    :param language: Language code (defaults to CONFIG.bot.language)
    :return: Discord Embed
    """
    if not language:
        language = CONFIG.bot.language

    template = load_embed_template("leave_confirmation", language)
    messages = template.get("MESSAGES", {})

    other_members = [m for m in team_data.get("members", []) if m != user_mention]
    has_partner = len(other_members) > 0

    if is_during_registration:
        # During registration - lighter consequences
        embed_template = template.get("LEAVE_DURING_REGISTRATION", {})

        # Build consequences list
        consequences = []
        consequences.append(messages.get("consequences_team_dissolved", "🔹 Your team will be dissolved"))

        if has_partner:
            msg = messages.get("consequences_partner_solo", "🔹 Your partner will be moved to solo queue")
            msg = msg.replace("PLACEHOLDER_PARTNER", other_members[0])
            consequences.append(msg)
            consequences.append(messages.get("consequences_partner_rematched", "🔹 They may be matched with another solo player"))

        consequences.append(messages.get("consequences_removed", "🔹 You will be completely removed"))
        consequences.append(messages.get("consequences_can_rejoin", "🔹 You can re-register"))

        # Replace placeholders in template
        placeholders = {
            "PLACEHOLDER_TEAM_NAME": team_name,
            "PLACEHOLDER_CONSEQUENCES": "\n".join(consequences)
        }

    else:
        # After registration - serious consequences
        embed_template = template.get("LEAVE_AFTER_REGISTRATION", {})

        tournament = load_tournament_data()
        matches = tournament.get("matches", [])

        # Count open matches
        open_match_count = sum(
            1 for m in matches
            if team_name in (m.get("team1"), m.get("team2")) and m.get("status") == "open"
        )

        # Build consequences list
        consequences = []
        consequences.append(messages.get("consequences_withdrawn", "🔹 Your team will be marked as WITHDRAWN"))

        msg = messages.get("consequences_forfeited", "🔹 {count} match(es) will be forfeited")
        msg = msg.replace("PLACEHOLDER_MATCH_COUNT", str(open_match_count))
        consequences.append(msg)

        consequences.append(messages.get("consequences_auto_loss", "🔹 All forfeited matches count as automatic losses"))
        consequences.append(messages.get("consequences_auto_win", "🔹 Your opponents will receive automatic wins"))

        if has_partner:
            msg = messages.get("consequences_partner_eliminated", "🔹 Your partner will also be eliminated")
            msg = msg.replace("PLACEHOLDER_PARTNER", other_members[0])
            consequences.append(msg)

        consequences.append(messages.get("consequences_irreversible", "🔹 This action CANNOT BE UNDONE"))
        consequences.append(messages.get("consequences_no_rejoin", "🔹 You CANNOT re-join this tournament"))

        # Partner impact
        if has_partner:
            partner_impact = messages.get("partner_impact_text", "Your partner will be notified...")
        else:
            partner_impact = messages.get("partner_impact_none", "Your team will be removed...")

        # Replace placeholders in template
        placeholders = {
            "PLACEHOLDER_TEAM_NAME": team_name,
            "PLACEHOLDER_CONSEQUENCES": "\n".join(consequences),
            "PLACEHOLDER_PARTNER_IMPACT": partner_impact
        }

    return build_embed_from_template(embed_template, placeholders)
