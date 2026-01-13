"""
Availability Conflict Resolver

Detects and resolves availability conflicts between teams.
Uses locale system for internationalization.
"""

from typing import List, Dict, Set, Tuple, Optional
from datetime import datetime
from zoneinfo import ZoneInfo
import discord

from modules.dataStorage import load_tournament_data, save_tournament_data
from modules.logger import logger
from modules.config import CONFIG
from modules.utils import AvailabilityChecker
from modules.matchmaker import (
    get_valid_slots_for_match,
    generate_slot_matrix
)
from modules.availability_conflict_view import (
    AvailabilityConflictView,
    generate_availability_suggestions
)
from modules.embeds import load_embed_template, build_embed_from_template


class ConflictResolutionCoordinator:
    """
    Coordinates the resolution of availability conflicts.
    Manages the workflow from detection to resolution.
    """

    def __init__(self, channel: discord.TextChannel):
        self.channel = channel
        self.pending_resolutions: Set[int] = set()
        self.excluded_teams: Set[str] = set()
        self.resolved_matches: Dict[int, datetime] = {}
        self.language = CONFIG.bot.language

        # Load locale messages
        template = load_embed_template("availability_conflict", self.language)
        self.messages = template.get("MESSAGES", {})
        self.embed_template = template.get("CONFLICT_NOTIFICATION", {})

    async def detect_and_resolve_conflicts(self) -> bool:
        """
        Detect matches with no overlapping availability and initiate resolution.

        :return: True if conflicts were found and resolution started, False otherwise
        """
        tournament = load_tournament_data()
        matches = tournament.get("matches", [])
        teams = tournament.get("teams", {})

        # Find unassigned matches
        unassigned_matches = [m for m in matches if not m.get("scheduled_time")]

        if not unassigned_matches:
            logger.info("[CONFLICT-RESOLVER] No unassigned matches - no conflicts to resolve.")
            return False

        logger.info(f"[CONFLICT-RESOLVER] Found {len(unassigned_matches)} unassigned matches")

        # Generate slot matrix to check which matches have NO availability overlap
        slot_matrix = generate_slot_matrix(tournament)

        conflicts = []
        for match in unassigned_matches:
            team1 = match["team1"]
            team2 = match["team2"]
            match_id = match["match_id"]

            # Check if teams have ANY common availability
            valid_slots = get_valid_slots_for_match(team1, team2, slot_matrix)

            if not valid_slots:
                # No common availability at all - this is a conflict!
                logger.warning(
                    f"[CONFLICT-RESOLVER] Match {match_id} ({team1} vs {team2}) "
                    f"has NO overlapping availability!"
                )
                conflicts.append(match)
            else:
                logger.info(
                    f"[CONFLICT-RESOLVER] Match {match_id} ({team1} vs {team2}) "
                    f"has {len(valid_slots)} potential slots (not a conflict, just scheduling issue)"
                )

        if not conflicts:
            logger.info("[CONFLICT-RESOLVER] No availability conflicts found - all unassigned matches have potential slots.")
            return False

        # Conflicts found - notify and start resolution process
        logger.warning(f"[CONFLICT-RESOLVER] Found {len(conflicts)} matches with availability conflicts!")

        msg_template = self.messages.get(
            "conflicts_detected",
            "⚠️ **Availability Conflicts Detected**\nFound {count} match(es) where teams have no overlapping availability.\nStarting conflict resolution process..."
        )
        msg = msg_template.replace("PLACEHOLDER_COUNT", str(len(conflicts)))
        await self.channel.send(msg)

        # Start resolution for each conflict
        for match in conflicts:
            await self._initiate_conflict_resolution(match)

        return True

    async def _initiate_conflict_resolution(self, match: dict):
        """
        Start the resolution process for a single match conflict.

        :param match: Match data dict
        """
        match_id = match["match_id"]
        team1 = match["team1"]
        team2 = match["team2"]

        if match_id in self.pending_resolutions:
            logger.warning(f"[CONFLICT-RESOLVER] Match {match_id} already has pending resolution")
            return

        self.pending_resolutions.add(match_id)

        tournament = load_tournament_data()
        teams = tournament.get("teams", {})
        team1_data = teams.get(team1, {})
        team2_data = teams.get(team2, {})

        # Get team members
        team1_members = await self._get_team_members(team1, team1_data)
        team2_members = await self._get_team_members(team2, team2_data)

        if not team1_members or not team2_members:
            logger.error(
                f"[CONFLICT-RESOLVER] Could not find members for match {match_id}. "
                f"Skipping conflict resolution."
            )
            self.pending_resolutions.discard(match_id)
            return

        # Generate time slot suggestions
        tz = ZoneInfo(CONFIG.bot.timezone)
        tournament_start = datetime.fromisoformat(tournament["registration_end"])
        tournament_end = datetime.fromisoformat(tournament["tournament_end"])

        if tournament_start.tzinfo is None:
            tournament_start = tournament_start.replace(tzinfo=tz)
        if tournament_end.tzinfo is None:
            tournament_end = tournament_end.replace(tzinfo=tz)

        suggested_slots = generate_availability_suggestions(
            team1_data,
            team2_data,
            tournament_start,
            tournament_end,
            count=10
        )

        logger.info(
            f"[CONFLICT-RESOLVER] Generated {len(suggested_slots)} suggestions "
            f"for match {match_id}"
        )

        # Create embed for conflict notification using locale template
        team1_avail_str = self._format_availability(team1_data.get("availability", {}))
        team2_avail_str = self._format_availability(team2_data.get("availability", {}))

        no_avail_msg = self.messages.get("no_availability", "No availability set")

        placeholders = {
            "PLACEHOLDER_MATCH_ID": str(match_id),
            "PLACEHOLDER_TEAM1": team1,
            "PLACEHOLDER_TEAM2": team2,
            "PLACEHOLDER_TEAM1_AVAIL": team1_avail_str or no_avail_msg,
            "PLACEHOLDER_TEAM2_AVAIL": team2_avail_str or no_avail_msg
        }

        embed = build_embed_from_template(self.embed_template, placeholders)

        # Create view
        view = AvailabilityConflictView(
            match_id=match_id,
            team1=team1,
            team2=team2,
            team1_members=team1_members,
            team2_members=team2_members,
            suggested_slots=suggested_slots,
            on_resolution_callback=self._handle_resolution
        )

        # Send message with view
        message = await self.channel.send(
            content=f"🔔 {' '.join(m.mention for m in team1_members + team2_members)}",
            embed=embed,
            view=view
        )
        view.message = message

        logger.info(f"[CONFLICT-RESOLVER] Sent conflict resolution request for match {match_id}")

    async def _get_team_members(self, team_name: str, team_data: dict) -> List[discord.Member]:
        """
        Get Discord Member objects for a team.

        :param team_name: Team name
        :param team_data: Team data dict
        :return: List of Member objects
        """
        members = []
        for member_mention in team_data.get("members", []):
            try:
                from modules.utils import extract_user_id
                user_id = extract_user_id(member_mention)
                if user_id:
                    member = self.channel.guild.get_member(user_id)
                    if member:
                        members.append(member)
                    else:
                        logger.warning(
                            f"[CONFLICT-RESOLVER] Could not find member {user_id} in guild"
                        )
                else:
                    logger.error(
                        f"[CONFLICT-RESOLVER] Could not extract user ID from mention: {member_mention}"
                    )
            except (ValueError, AttributeError) as e:
                logger.error(
                    f"[CONFLICT-RESOLVER] Error parsing member mention {member_mention}: {e}"
                )

        return members

    def _format_availability(self, availability: dict) -> str:
        """
        Format availability dict for display.

        :param availability: Availability dict
        :return: Formatted string
        """
        if not availability:
            return self.messages.get("no_times_set", "No times set")

        lines = []
        for day in ["saturday", "sunday", "monday", "tuesday", "wednesday", "thursday", "friday"]:
            time_range = availability.get(day, "00:00-00:00")
            if time_range != "00:00-00:00":
                lines.append(f"• {day.capitalize()}: {time_range}")

        return "\n".join(lines) if lines else self.messages.get("no_availability", "No availability")

    async def _handle_resolution(
        self,
        match_id: int,
        team1: str,
        team2: str,
        selected_slot: Optional[datetime] = None,
        excluded_team: Optional[str] = None
    ):
        """
        Handle the resolution of a conflict.

        :param match_id: Match ID
        :param team1: First team name
        :param team2: Second team name
        :param selected_slot: Agreed time slot (if any)
        :param excluded_team: Team to exclude ("both", team name, or None)
        """
        logger.info(
            f"[CONFLICT-RESOLVER] Handling resolution for match {match_id}: "
            f"slot={selected_slot}, excluded={excluded_team}"
        )

        tournament = load_tournament_data()
        teams = tournament.get("teams", {})

        if excluded_team:
            # Handle team exclusion
            teams_to_exclude = []

            if excluded_team == "both":
                teams_to_exclude = [team1, team2]
            else:
                teams_to_exclude = [excluded_team]

            for team in teams_to_exclude:
                if team not in self.excluded_teams:
                    self.excluded_teams.add(team)
                    await self._exclude_team(team)

        elif selected_slot:
            # Update team availability to include the selected slot
            await self._update_team_availability(team1, team2, selected_slot)
            self.resolved_matches[match_id] = selected_slot

        self.pending_resolutions.discard(match_id)

        # Check if all conflicts are resolved
        if not self.pending_resolutions:
            await self._finalize_all_resolutions()

    async def _exclude_team(self, team_name: str):
        """
        Exclude a team from the tournament by forfeiting all their matches.

        :param team_name: Team to exclude
        """
        logger.warning(f"[CONFLICT-RESOLVER] Excluding team {team_name} from tournament")

        tournament = load_tournament_data()
        teams = tournament.get("teams", {})

        # Mark team as excluded
        if team_name in teams:
            teams[team_name]["status"] = "excluded"
            teams[team_name]["excluded_reason"] = "availability_conflict"

        # Forfeit all open matches for this team
        forfeited_count = 0
        for match in tournament.get("matches", []):
            if match.get("status") == "open" and team_name in (match.get("team1"), match.get("team2")):
                match["status"] = "forfeit"
                match["forfeit_by"] = team_name

                # Opponent wins (unless also excluded)
                opponent = match["team2"] if match["team1"] == team_name else match["team1"]
                opponent_status = teams.get(opponent, {}).get("status")

                if opponent_status in ("excluded", "withdrawn"):
                    match["winner"] = "None (both teams excluded/withdrawn)"
                else:
                    match["winner"] = opponent

                forfeited_count += 1

        save_tournament_data(tournament)

        msg_template = self.messages.get(
            "team_excluded",
            "⚠️ Team **{team}** has been excluded from the tournament.\n📊 {count} match(es) forfeited."
        )
        msg = msg_template.replace("PLACEHOLDER_TEAM", team_name)
        msg = msg.replace("PLACEHOLDER_COUNT", str(forfeited_count))
        await self.channel.send(msg)

        logger.info(f"[CONFLICT-RESOLVER] Team {team_name} excluded, {forfeited_count} matches forfeited")

    async def _update_team_availability(self, team1: str, team2: str, slot: datetime):
        """
        Update both teams' availability to include the agreed time slot.

        :param team1: First team name
        :param team2: Second team name
        :param slot: Agreed datetime slot
        """
        logger.info(
            f"[CONFLICT-RESOLVER] Updating availability for {team1} and {team2} "
            f"to include slot {slot}"
        )

        tournament = load_tournament_data()
        teams = tournament.get("teams", {})

        # Determine day and time
        weekday = slot.weekday()
        day_key = AvailabilityChecker.DAY_NAMES[weekday]
        slot_time = slot.strftime("%H:%M")

        # Add 2-hour window around the slot
        from datetime import timedelta
        start_time = (slot - timedelta(hours=1)).strftime("%H:%M")
        end_time = (slot + timedelta(hours=1)).strftime("%H:%M")
        new_range = f"{start_time}-{end_time}"

        # Update both teams
        for team_name in [team1, team2]:
            if team_name in teams:
                availability = teams[team_name].get("availability", {})
                current_range = availability.get(day_key, "00:00-00:00")

                if current_range == "00:00-00:00":
                    # No existing availability on this day - set it
                    availability[day_key] = new_range
                else:
                    # Merge with existing availability
                    availability[day_key] = self._merge_time_ranges(current_range, new_range)

                teams[team_name]["availability"] = availability
                logger.info(
                    f"[CONFLICT-RESOLVER] Updated {team_name} availability for {day_key}: "
                    f"{availability[day_key]}"
                )

        save_tournament_data(tournament)

        msg_template = self.messages.get(
            "availability_updated",
            "✅ Updated availability for **{team1}** and **{team2}** to include **{slot}**"
        )
        msg = msg_template.replace("PLACEHOLDER_TEAM1", team1)
        msg = msg.replace("PLACEHOLDER_TEAM2", team2)
        msg = msg.replace("PLACEHOLDER_SLOT", slot.strftime('%A %d.%m.%Y %H:%M'))
        await self.channel.send(msg)

    def _merge_time_ranges(self, range1: str, range2: str) -> str:
        """
        Merge two time ranges into a single encompassing range.

        :param range1: First time range (e.g., "14:00-18:00")
        :param range2: Second time range (e.g., "16:00-20:00")
        :return: Merged range (e.g., "14:00-20:00")
        """
        try:
            start1, end1 = AvailabilityChecker.parse_time_range(range1)
            start2, end2 = AvailabilityChecker.parse_time_range(range2)

            earliest_start = min(start1, start2)
            latest_end = max(end1, end2)

            return f"{earliest_start.strftime('%H:%M')}-{latest_end.strftime('%H:%M')}"
        except ValueError as e:
            logger.error(f"[CONFLICT-RESOLVER] Error merging time ranges: {e}")
            return range2  # Fall back to new range

    async def _finalize_all_resolutions(self):
        """
        Called when all conflicts are resolved.
        Regenerates the schedule and publishes it.
        """
        logger.info("[CONFLICT-RESOLVER] All conflicts resolved! Regenerating schedule...")

        msg = self.messages.get(
            "all_resolved",
            "✅ All availability conflicts have been resolved!\n🔄 Regenerating tournament schedule..."
        )
        await self.channel.send(msg)

        # Regenerate schedule with updated availability
        from modules.matchmaker import generate_and_assign_slots, generate_schedule_overview

        await generate_and_assign_slots()

        # Reload and display schedule
        tournament = load_tournament_data()
        matches = tournament.get("matches", [])

        from modules.embeds import send_match_schedule_for_channel
        description_text = generate_schedule_overview(matches)
        await send_match_schedule_for_channel(self.channel, description_text)

        logger.info("[CONFLICT-RESOLVER] Schedule regenerated and published!")
