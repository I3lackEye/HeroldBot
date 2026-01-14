"""
Availability Conflict Resolution System

Handles cases where teams have no overlapping availability.
Provides suggestions for alternative time slots and manages team responses.
Uses locale system for internationalization.
"""

from discord import ui, ButtonStyle, Interaction, Member, SelectOption, Embed
from typing import List, Dict, Set, Optional
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import asyncio

from modules.dataStorage import load_tournament_data, save_tournament_data
from modules.logger import logger
from modules.config import CONFIG
from modules.utils import AvailabilityChecker
from modules.embeds import load_embed_template


class AvailabilityConflictView(ui.View):
    """
    View for resolving availability conflicts between teams.
    Both teams must agree to a proposed time slot, or they will be excluded.
    """

    def __init__(
        self,
        match_id: int,
        team1: str,
        team2: str,
        team1_members: List[Member],
        team2_members: List[Member],
        suggested_slots: List[datetime],
        on_resolution_callback
    ):
        super().__init__(timeout=172800)  # 48 hours timeout
        self.match_id = match_id
        self.team1 = team1
        self.team2 = team2
        self.team1_members = team1_members
        self.team2_members = team2_members
        self.all_members = team1_members + team2_members
        self.suggested_slots = suggested_slots
        self.on_resolution_callback = on_resolution_callback
        self.language = CONFIG.bot.language

        self.approved = set()  # Track who approved
        self.selected_slot = None
        self.message = None

        # Load locale messages
        template = load_embed_template("availability_conflict", self.language)
        self.messages = template.get("MESSAGES", {})

        # Create select menu with suggested slots
        self._add_slot_selector()

    def _add_slot_selector(self):
        """Add dropdown menu with time slot suggestions."""
        options = []

        # Add up to 10 suggested slots
        for i, slot in enumerate(self.suggested_slots[:10]):
            label = slot.strftime("%a %d.%m.%Y %H:%M")
            value = slot.isoformat()

            desc_template = self.messages.get("option_label", "Option {num}")
            desc = desc_template.replace("PLACEHOLDER_NUM", str(i + 1))

            options.append(SelectOption(
                label=label,
                value=value,
                description=desc
            ))

        if not options:
            no_sugg = self.messages.get("no_suggestions", "No suggestions available")
            no_sugg_desc = self.messages.get("no_suggestions_desc", "Cannot find common time")
            options.append(SelectOption(
                label=no_sugg,
                value="none",
                description=no_sugg_desc
            ))

        placeholder = self.messages.get("select_placeholder", "Select a time slot that works for both teams...")
        select = ui.Select(
            placeholder=placeholder,
            options=options,
            min_values=1,
            max_values=1
        )
        select.callback = self.slot_selected
        self.add_item(select)

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Only team members can interact."""
        if interaction.user not in self.all_members:
            msg = self.messages.get("not_part_of_match", "🚫 You are not part of this match.")
            await interaction.response.send_message(msg, ephemeral=True)
            return False
        return True

    async def slot_selected(self, interaction: Interaction):
        """Called when a slot is selected from dropdown."""
        selected_value = interaction.data["values"][0]

        if selected_value == "none":
            msg = self.messages.get("no_slot_selected", "❌ No time slots available. Please decline to withdraw from the tournament.")
            await interaction.response.send_message(msg, ephemeral=True)
            return

        self.selected_slot = datetime.fromisoformat(selected_value)

        msg_template = self.messages.get("selected_slot", "✅ You selected: **{slot}**\nWaiting for all players to confirm...")
        msg = msg_template.replace("PLACEHOLDER_SLOT", self.selected_slot.strftime('%A %d.%m.%Y %H:%M'))
        await interaction.response.send_message(msg, ephemeral=True)

        # Automatically "approve" for this user
        if interaction.user not in self.approved:
            self.approved.add(interaction.user)
            logger.info(
                f"[AVAILABILITY-CONFLICT] {interaction.user.display_name} selected and approved "
                f"slot {self.selected_slot} for match {self.match_id}"
            )

        # Check if all players approved
        await self._check_full_approval()

    @ui.button(label="✅ Confirm Selected Time", style=ButtonStyle.success)
    async def confirm(self, interaction: Interaction, button: ui.Button):
        """Confirm the currently selected time slot."""
        if not self.selected_slot:
            msg = self.messages.get("no_slot_selected", "⚠️ Please select a time slot first using the dropdown menu above.")
            await interaction.response.send_message(msg, ephemeral=True)
            return

        if interaction.user in self.approved:
            msg = self.messages.get("already_confirmed", "✅ You already confirmed this time slot.")
            await interaction.response.send_message(msg, ephemeral=True)
            return

        self.approved.add(interaction.user)
        logger.info(
            f"[AVAILABILITY-CONFLICT] {interaction.user.display_name} confirmed "
            f"slot {self.selected_slot} for match {self.match_id}"
        )

        msg_template = self.messages.get("confirmed_count", "✅ Confirmed! ({current}/{total} players)")
        msg = msg_template.replace("PLACEHOLDER_CURRENT", str(len(self.approved)))
        msg = msg_template.replace("PLACEHOLDER_TOTAL", str(len(self.all_members)))
        await interaction.response.send_message(msg, ephemeral=True)

        # Check if all players approved
        await self._check_full_approval()

    @ui.button(label="❌ Decline (Withdraw from Tournament)", style=ButtonStyle.danger)
    async def decline(self, interaction: Interaction, button: ui.Button):
        """
        Decline to adjust availability.
        This will withdraw the declining player's team from the tournament.
        """
        await interaction.response.defer()

        # Determine which team the declining player belongs to
        tournament = load_tournament_data()
        teams = tournament.get("teams", {})

        decliner_team = None
        if interaction.user in self.team1_members:
            decliner_team = self.team1
        elif interaction.user in self.team2_members:
            decliner_team = self.team2

        if not decliner_team:
            logger.error(
                f"[AVAILABILITY-CONFLICT] Could not find team for declining player "
                f"{interaction.user.mention}"
            )
            await interaction.followup.send(
                "❌ Error: Could not determine your team.",
                ephemeral=True
            )
            return

        logger.warning(
            f"[AVAILABILITY-CONFLICT] {interaction.user.display_name} from team "
            f"{decliner_team} DECLINED to adjust availability for match {self.match_id}"
        )

        # Mark team as excluded (will be handled by callback)
        opponent = self.team2 if decliner_team == self.team1 else self.team1

        if self.message:
            msg_template = self.messages.get(
                "declined_team",
                "❌ **{user}** (Team **{team}**) declined to adjust availability.\n"
                "⚠️ Team **{team}** will be excluded from the tournament.\n"
                "🏆 Team **{opponent}** receives a walkover for this match."
            )
            msg = msg_template.replace("PLACEHOLDER_USER", interaction.user.mention)
            msg = msg.replace("PLACEHOLDER_TEAM", decliner_team)
            msg = msg.replace("PLACEHOLDER_OPPONENT", opponent)

            await self.message.edit(content=msg, embed=None, view=None)

        # Call resolution callback with exclusion
        await self.on_resolution_callback(
            self.match_id,
            decliner_team,
            None,
            excluded_team=decliner_team
        )

        self.stop()

    async def _check_full_approval(self):
        """Check if all players have approved the selected slot."""
        if self.approved == set(self.all_members):
            await self._finalize_resolution()

    async def _finalize_resolution(self):
        """All players agreed - update availability and reschedule."""
        logger.info(
            f"[AVAILABILITY-CONFLICT] All players approved slot {self.selected_slot} "
            f"for match {self.match_id}. Updating availability..."
        )

        if self.message:
            msg_template = self.messages.get(
                "all_agreed",
                "✅ All players agreed to the new time slot!\n"
                "📅 Match {match_id} will be scheduled for **{slot}**\n"
                "⏳ Updating team availability and regenerating schedule..."
            )
            msg = msg_template.replace("PLACEHOLDER_MATCH_ID", str(self.match_id))
            msg = msg.replace("PLACEHOLDER_SLOT", self.selected_slot.strftime('%A %d.%m.%Y %H:%M'))

            await self.message.edit(content=msg, embed=None, view=None)

        # Call resolution callback
        await self.on_resolution_callback(
            self.match_id,
            self.team1,
            self.team2,
            self.selected_slot
        )

        self.stop()

    async def on_timeout(self):
        """
        Timeout after 48 hours - both teams will be excluded.
        """
        logger.warning(
            f"[AVAILABILITY-CONFLICT] Timeout for match {self.match_id}. "
            f"Both teams ({self.team1}, {self.team2}) will be excluded."
        )

        if self.message:
            msg_template = self.messages.get(
                "timeout_both",
                "⌛ **Timeout!**\n"
                "No agreement was reached within 48 hours.\n"
                "⚠️ Both teams (**{team1}**, **{team2}**) will be excluded from the tournament."
            )
            msg = msg_template.replace("PLACEHOLDER_TEAM1", self.team1)
            msg = msg.replace("PLACEHOLDER_TEAM2", self.team2)

            await self.message.edit(content=msg, embed=None, view=None)

        # Exclude both teams
        await self.on_resolution_callback(
            self.match_id,
            self.team1,
            self.team2,
            None,
            excluded_team="both"
        )

        self.stop()


def generate_availability_suggestions(
    team1_data: dict,
    team2_data: dict,
    tournament_start: datetime,
    tournament_end: datetime,
    count: int = 10
) -> List[datetime]:
    """
    Generate suggested time slots for teams with no overlapping availability.

    Strategy:
    1. Find times when at least one team is available
    2. Prefer times when both teams have partial availability
    3. Spread suggestions across different days

    :param team1_data: Team 1 tournament data
    :param team2_data: Team 2 tournament data
    :param tournament_start: Tournament start datetime
    :param tournament_end: Tournament end datetime
    :param count: Number of suggestions to generate
    :return: List of suggested datetime slots
    """
    suggestions = []
    tz = ZoneInfo(CONFIG.bot.timezone)

    # Ensure timezone awareness
    if tournament_start.tzinfo is None:
        tournament_start = tournament_start.replace(tzinfo=tz)
    if tournament_end.tzinfo is None:
        tournament_end = tournament_end.replace(tzinfo=tz)

    team1_avail = team1_data.get("availability", {})
    team2_avail = team2_data.get("availability", {})

    # Collect all time ranges from both teams
    all_ranges = set()
    for day, time_range in team1_avail.items():
        if time_range != "00:00-00:00":
            all_ranges.add((day, time_range))
    for day, time_range in team2_avail.items():
        if time_range != "00:00-00:00":
            all_ranges.add((day, time_range))

    current = tournament_start
    while current <= tournament_end and len(suggestions) < count:
        weekday = current.weekday()
        day_key = AvailabilityChecker.DAY_NAMES[weekday]

        # Check if this day has any availability for either team
        team1_range = team1_avail.get(day_key, "00:00-00:00")
        team2_range = team2_avail.get(day_key, "00:00-00:00")

        if team1_range != "00:00-00:00" or team2_range != "00:00-00:00":
            # At least one team has availability on this day
            # Suggest midpoint times in each team's availability

            if team1_range != "00:00-00:00":
                try:
                    start, end = AvailabilityChecker.parse_time_range(team1_range)
                    # Calculate midpoint
                    start_dt = datetime.combine(current.date(), start, tzinfo=tz)
                    end_dt = datetime.combine(current.date(), end, tzinfo=tz)
                    midpoint = start_dt + (end_dt - start_dt) / 2

                    if midpoint not in suggestions:
                        suggestions.append(midpoint)
                except ValueError:
                    pass

            if team2_range != "00:00-00:00" and len(suggestions) < count:
                try:
                    start, end = AvailabilityChecker.parse_time_range(team2_range)
                    start_dt = datetime.combine(current.date(), start, tzinfo=tz)
                    end_dt = datetime.combine(current.date(), end, tzinfo=tz)
                    midpoint = start_dt + (end_dt - start_dt) / 2

                    if midpoint not in suggestions:
                        suggestions.append(midpoint)
                except ValueError:
                    pass

        current += timedelta(days=1)

    # If we don't have enough suggestions, add some standard times
    if len(suggestions) < count:
        current = tournament_start
        while current <= tournament_end and len(suggestions) < count:
            # Add standard times: 14:00, 18:00, 20:00
            for hour in [14, 18, 20]:
                suggestion = current.replace(hour=hour, minute=0, second=0, microsecond=0)
                if suggestion not in suggestions and tournament_start <= suggestion <= tournament_end:
                    suggestions.append(suggestion)
                    if len(suggestions) >= count:
                        break
            current += timedelta(days=1)

    return sorted(suggestions)[:count]
