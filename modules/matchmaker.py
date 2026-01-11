# matchmaker.py
import json
import logging
import os
import random
from collections import defaultdict
from datetime import datetime, time, timedelta
from itertools import combinations
from zoneinfo import ZoneInfo
from math import ceil
from typing import Dict, List, Optional, Tuple

from discord import TextChannel

# Local modules
from modules.config import CONFIG
from modules.dataStorage import DEBUG_MODE, load_tournament_data, save_tournament_data
# Removed: send_cleanup_summary import - function deleted to reduce spam
from modules.logger import logger
from modules.utils import generate_team_name, get_active_days_config, get_default_availability

# Tournament configuration (from centralized config)
MATCH_DURATION = CONFIG.tournament.match_duration
PAUSE_DURATION = CONFIG.tournament.pause_duration
MAX_TIME_BUDGET = CONFIG.tournament.max_time_budget


# ---------------------------------------
# Availability Checker Class
# ---------------------------------------
class AvailabilityChecker:
    """
    Centralized availability and time range logic.
    Handles all team availability checking, time range parsing, and overlap calculations.
    """

    # Day name mapping
    DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

    @staticmethod
    def parse_time_range(range_str: str) -> Tuple[time, time]:
        """
        Parses a time range string 'HH:MM-HH:MM' into (start_time, end_time).

        :param range_str: Time range as string (e.g., "14:00-18:00")
        :return: Tuple of (start_time, end_time)
        :raises ValueError: If parsing fails
        """
        try:
            start_str, end_str = range_str.split("-")
            start_time = datetime.strptime(start_str.strip(), "%H:%M").time()
            end_time = datetime.strptime(end_str.strip(), "%H:%M").time()
            return start_time, end_time
        except Exception as e:
            raise ValueError(f"Invalid time range format: {range_str}") from e

    @staticmethod
    def calculate_overlap(range1: str, range2: str) -> str:
        """
        Calculates the overlap between two time ranges.

        :param range1: First time range (e.g., "12:00-18:00")
        :param range2: Second time range (e.g., "14:00-20:00")
        :return: Overlapping range as string, or "00:00-00:00" if no overlap
        """
        try:
            start1, end1 = AvailabilityChecker.parse_time_range(range1)
            start2, end2 = AvailabilityChecker.parse_time_range(range2)

            # Convert to datetime for comparison (date doesn't matter, just time)
            today = datetime.today().date()
            start1_dt = datetime.combine(today, start1)
            end1_dt = datetime.combine(today, end1)
            start2_dt = datetime.combine(today, start2)
            end2_dt = datetime.combine(today, end2)

            latest_start = max(start1_dt, start2_dt)
            earliest_end = min(end1_dt, end2_dt)

            if latest_start >= earliest_end:
                return "00:00-00:00"  # No overlap

            return f"{latest_start.strftime('%H:%M')}-{earliest_end.strftime('%H:%M')}"
        except ValueError:
            logger.warning(f"[AVAILABILITY] Error calculating overlap: {range1} vs {range2}")
            return "00:00-00:00"

    @staticmethod
    def merge_availability(avail1: dict, avail2: dict, days: Optional[List[str]] = None) -> dict:
        """
        Merges two availability dictionaries by calculating overlap for each day.

        :param avail1: First availability dict (e.g., {"saturday": "12:00-18:00"})
        :param avail2: Second availability dict
        :param days: List of days to merge (defaults to saturday/sunday)
        :return: Merged availability dict with overlapping time ranges
        """
        if days is None:
            days = ["saturday", "sunday"]

        result = {}
        for day in days:
            range1 = avail1.get(day, "00:00-00:00")
            range2 = avail2.get(day, "00:00-00:00")
            result[day] = AvailabilityChecker.calculate_overlap(range1, range2)

        return result

    @staticmethod
    def is_time_in_range(time_to_check: time, time_range: str) -> bool:
        """
        Checks if a specific time falls within a time range.

        :param time_to_check: The time to check
        :param time_range: Time range string (e.g., "14:00-18:00")
        :return: True if time is within range
        """
        if not time_range or time_range == "00:00-00:00":
            return False

        try:
            start_time, end_time = AvailabilityChecker.parse_time_range(time_range)
            return start_time <= time_to_check < end_time
        except ValueError:
            return False

    @staticmethod
    def is_available_at(team_data: dict, slot_datetime: datetime) -> bool:
        """
        Checks if a team is available at the given datetime.

        :param team_data: Team data dict with 'availability' field
        :param slot_datetime: The datetime to check
        :return: True if team is available
        """
        weekday = slot_datetime.weekday()
        day_key = AvailabilityChecker.DAY_NAMES[weekday]

        availability = team_data.get("availability", {})
        time_range = availability.get(day_key)

        if not time_range:
            return False

        return AvailabilityChecker.is_time_in_range(slot_datetime.time(), time_range)

    @staticmethod
    def is_slot_blacklisted(team_data: dict, slot_datetime: datetime) -> bool:
        """
        Checks if a slot datetime is in the team's blacklisted dates.

        :param team_data: Team data dict with optional 'unavailable_dates' field
        :param slot_datetime: The datetime to check
        :return: True if slot is blacklisted
        """
        unavailable_dates = set(team_data.get("unavailable_dates", []))
        slot_date_str = slot_datetime.strftime("%Y-%m-%d")
        return slot_date_str in unavailable_dates

    @staticmethod
    def is_team_available_for_slot(team_data: dict, slot_datetime: datetime) -> bool:
        """
        Complete availability check: both time range AND blacklist.

        :param team_data: Team data dict
        :param slot_datetime: The datetime to check
        :return: True if team is available (not blacklisted AND within time range)
        """
        if AvailabilityChecker.is_slot_blacklisted(team_data, slot_datetime):
            return False

        return AvailabilityChecker.is_available_at(team_data, slot_datetime)

    @staticmethod
    def has_any_overlap(availability: dict) -> bool:
        """
        Checks if an availability dict has any actual availability.

        :param availability: Availability dict
        :return: True if at least one day has availability
        """
        if not availability:
            return False
        return any(val != "00:00-00:00" for val in availability.values())

    @staticmethod
    def get_available_days(availability: dict) -> List[str]:
        """
        Returns list of days where team has availability.

        :param availability: Availability dict
        :return: List of day names with non-zero availability
        """
        return [day for day, time_range in availability.items() if time_range != "00:00-00:00"]

    @staticmethod
    def can_fit_match(team_data: dict, slot_datetime: datetime, match_duration: timedelta) -> bool:
        """
        Checks if a team has enough time remaining in their availability window
        to complete a full match starting at the given slot.

        :param team_data: Team data dict with 'availability' field
        :param slot_datetime: The proposed match start time
        :param match_duration: How long the match takes
        :return: True if match can be completed within availability window
        """
        weekday = slot_datetime.weekday()
        day_key = AvailabilityChecker.DAY_NAMES[weekday]

        availability = team_data.get("availability", {})
        time_range = availability.get(day_key)

        if not time_range or time_range == "00:00-00:00":
            return False

        try:
            start_time, end_time = AvailabilityChecker.parse_time_range(time_range)

            # Calculate when match would end
            match_end = slot_datetime + match_duration
            match_end_time = match_end.time()

            # Check if match start is within availability
            if not (start_time <= slot_datetime.time() < end_time):
                return False

            # Check if match end is within availability (or before)
            # Note: We use <= for end_time because the match should finish by then
            return match_end_time <= end_time

        except ValueError:
            return False


# =======================================
# TEAM MANAGEMENT FUNCTIONS
# =======================================

def auto_match_solo():
    """
    Pairs solo players based on common availability for Saturday/Sunday.
    Only saves working teams.
    """
    tournament = load_tournament_data()
    solo_players = tournament.get("solo", [])

    if len(solo_players) < 2:
        logger.info("[MATCHMAKER] Not enough solo players to pair.")
        return []

    logger.debug(f"[MATCHMAKER] Solo players (raw data): {solo_players}")

    random.shuffle(solo_players)
    new_teams = {}
    used_names = set(tournament.get("teams", {}).keys())

    while len(solo_players) >= 2:
        p1 = solo_players.pop()
        p2 = solo_players.pop()
        name1 = p1.get("player", "???")
        name2 = p2.get("player", "???")

        logger.debug(f"[MATCHMAKER] Pairing: {name1} + {name2}")

        avail1 = p1.get("availability", {})
        avail2 = p2.get("availability", {})

        # Use configured active days instead of hardcoded saturday/sunday
        active_days = get_active_days_config()
        overlap = AvailabilityChecker.merge_availability(avail1, avail2, days=active_days)

        # Validate that there's at least one day with actual overlap
        if not AvailabilityChecker.has_any_overlap(overlap):
            logger.warning(f"[MATCHMAKER] ❌ No common availability for {name1} and {name2} – Team will not be created.")
            continue

        # Log which days have overlap for debugging
        overlapping_days = AvailabilityChecker.get_available_days(overlap)
        logger.debug(f"[MATCHMAKER] ✅ Overlap found on: {', '.join(overlapping_days)}")

        team_name = generate_team_name()
        attempts = 0
        while team_name in used_names or team_name in new_teams:
            team_name = generate_team_name()
            attempts += 1
            if attempts > 10:
                logger.error("[MATCHMAKER] ❌ No unique team name found – Aborting this pairing.")
                logger.error(f"[MATCHMAKER]    Players {name1} and {name2} will remain in solo queue.")
                # Return players to solo queue instead of losing them
                solo_players.append(p1)
                solo_players.append(p2)
                break
        else:
            # Only create team if we successfully found a unique name
            used_names.add(team_name)

            new_teams[team_name] = {
                "members": [name1, name2],
                "availability": overlap,
            }

    if new_teams:
        tournament.setdefault("teams", {}).update(new_teams)
        tournament["solo"] = solo_players
        save_tournament_data(tournament)
        logger.info(f"[MATCHMAKER] ✅ {len(new_teams)} teams created: {', '.join(new_teams.keys())}")
    else:
        logger.warning("[MATCHMAKER] ❌ No teams created – nothing saved.")

    return list(new_teams.keys())


async def cleanup_orphan_teams(channel: TextChannel):
    """
    Removes teams with only 1 player after registration close
    and moves them to the solo list.
    """
    tournament = load_tournament_data()
    teams = tournament.get("teams", {})
    solo = tournament.get("solo", [])

    teams_deleted_list = []
    players_rescued_list = []

    for team_name, team_data in list(teams.items()):
        members = team_data.get("members", [])
        if len(members) == 1:
            # Only 1 player → dissolve
            player = members[0]
            solo.append(
                {
                    "player": player,
                    "availability": team_data.get("availability", get_default_availability()),
                    "unavailable_dates": team_data.get("unavailable_dates", [])
                }
            )
            del teams[team_name]
            teams_deleted_list.append(team_name)
            players_rescued_list.append(player)

    tournament["teams"] = teams
    tournament["solo"] = solo
    save_tournament_data(tournament)

    # Log cleanup results (no channel spam)
    if teams_deleted_list:
        logger.info(f"[CLEANUP] {len(teams_deleted_list)} orphan teams deleted: {', '.join(teams_deleted_list)}")
        logger.info(f"[CLEANUP] {len(players_rescued_list)} players moved to solo list")
    else:
        logger.info("[CLEANUP] No orphan teams found.")


# =======================================
# SCHEDULE GENERATION FUNCTIONS
# =======================================

def create_round_robin_schedule(tournament: dict):
    """
    Creates a round-robin schedule based on the current teams.
    """
    teams = list(tournament.get("teams", {}).keys())

    if len(teams) < 2:
        logger.warning("[MATCHMAKER] Not enough teams for a schedule.")
        return []

    matches = []
    match_id = 1

    for team1, team2 in combinations(teams, 2):
        matches.append(
            {
                "match_id": match_id,
                "team1": team1,
                "team2": team2,
                "status": "open",  # not yet played
                "scheduled_time": None,
            }
        )
        match_id += 1

    tournament["matches"] = matches
    save_tournament_data(tournament)

    logger.info(f"[MATCHMAKER] {len(matches)} matches created for {len(teams)} teams.")
    return matches


def generate_schedule_overview(matches: list) -> str:
    """
    Generates a nicely grouped schedule from the given match list.
    Highlights matches of TODAY with 🔥, completed matches with ✅.
    """
    logger.debug(f"[DEBUG] {len(matches)} matches received.")
    scheduled_count = sum(1 for m in matches if m.get("scheduled_time"))
    logger.debug(f"[DEBUG] Of which with scheduled_time: {scheduled_count}")

    if not matches:
        return "No matches scheduled."

    # Get timezone from config
    tz = ZoneInfo(CONFIG.bot.timezone)
    today = datetime.now(tz=tz).date()  # Today's date in configured timezone

    # Group by date
    schedule_by_day = defaultdict(list)
    for match in matches:
        scheduled_time = match.get("scheduled_time")
        if scheduled_time:
            dt = datetime.fromisoformat(scheduled_time)
            # Ensure timezone awareness
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            day = dt.strftime("%d.%m.%Y %A")
            schedule_by_day[day].append((dt, match))  # Store datetime + match

    description = ""
    for day, matches_list in sorted(
        schedule_by_day.items(),
        key=lambda x: datetime.strptime(x[0].split()[0], "%d.%m.%Y"),
    ):
        description += f"📅 {day}\n"

        # Sort matches on this day by time
        matches_list.sort(key=lambda x: x[0])  # x[0] is the datetime

        for dt, match in matches_list:
            team1 = match.get("team1", "Unknown")
            team2 = match.get("team2", "Unknown")
            match_status = match.get("status", "open")

            # Determine emoji
            if match_status == "forfeit":
                emoji = "⚠️"  # Forfeit match
                winner = match.get("winner", "Unknown")
                if "both teams withdrawn" in str(winner).lower():
                    description += f"{emoji} {dt.strftime('%H:%M')} – **{team1}** vs **{team2}** (Forfeit → No winner)\n"
                else:
                    description += f"{emoji} {dt.strftime('%H:%M')} – **{team1}** vs **{team2}** (Forfeit → {winner} wins)\n"
            elif match.get("rescue_assigned"):
                emoji = "❗"
                description += f"{emoji} {dt.strftime('%H:%M')} – **{team1}** vs **{team2}**\n"
            elif match_status == "completed":
                emoji = "✅"
                description += f"{emoji} {dt.strftime('%H:%M')} – **{team1}** vs **{team2}**\n"
            elif dt.date() == today:
                emoji = "🔥"
                description += f"{emoji} {dt.strftime('%H:%M')} – **{team1}** vs **{team2}**\n"
            else:
                emoji = "🕒"
                description += f"{emoji} {dt.strftime('%H:%M')} – **{team1}** vs **{team2}**\n"

        description += "\n"

    return description


def get_team_time_budget(team_name: str, date: datetime.date, matches: list) -> timedelta:
    """
    Calculates the total time a team is blocked on a specific day through matches + pauses.
    """
    # Get timezone from config
    tz = ZoneInfo(CONFIG.bot.timezone)
    total_time = timedelta()

    for match in matches:
        scheduled = match.get("scheduled_time")
        if not scheduled:
            continue

        try:
            match_time = datetime.fromisoformat(scheduled)
            # Ensure timezone awareness
            if match_time.tzinfo is None:
                match_time = match_time.replace(tzinfo=tz)
        except ValueError:
            continue

        if match_time.date() != date:
            continue

        if team_name in (match.get("team1"), match.get("team2")):
            total_time += MATCH_DURATION + PAUSE_DURATION

    return total_time


# =======================================
# SLOT GENERATION FUNCTIONS
# =======================================

def generate_slot_matrix(tournament: dict, slot_interval_minutes: int = 60) -> dict:
    """
    Creates a global slot matrix that indicates which teams are available at which slots.

    Improvements:
    - Configurable slot interval (default 60 minutes instead of 2 hours)
    - Validates that teams have enough time to complete a full match
    - Only generates slots where at least one team is available
    - Supports finer granularity (30-minute or 1-hour intervals)

    :param tournament: Tournament data dict
    :param slot_interval_minutes: Minutes between slots (default 60, can be 30 for finer granularity)
    :return: Dict[datetime, Set[team_name]]
    """
    from datetime import datetime, timedelta
    from collections import defaultdict

    # Get timezone from config
    tz = ZoneInfo(CONFIG.bot.timezone)

    # Parse dates and ensure they're timezone-aware
    from_date = datetime.fromisoformat(tournament["registration_end"])
    if from_date.tzinfo is None:
        from_date = from_date.replace(tzinfo=tz)

    to_date = datetime.fromisoformat(tournament["tournament_end"])
    if to_date.tzinfo is None:
        to_date = to_date.replace(tzinfo=tz)

    teams = tournament.get("teams", {})

    if not teams:
        logger.warning("[SLOT-MATRIX] No teams found, returning empty matrix.")
        return {}

    slot_matrix = defaultdict(set)
    slot_interval = timedelta(minutes=slot_interval_minutes)

    logger.info(f"[SLOT-MATRIX] Generating slots from {from_date} to {to_date} with {slot_interval_minutes}min intervals")
    logger.info(f"[SLOT-MATRIX] Using timezone: {CONFIG.bot.timezone}")

    current = from_date
    total_slots_generated = 0
    slots_with_teams = 0

    while current <= to_date:
        # Check each team's availability for this specific day
        weekday = current.weekday()
        day_key = AvailabilityChecker.DAY_NAMES[weekday]

        # Collect all team availability windows for this day
        day_has_available_teams = False
        for team_data in teams.values():
            availability = team_data.get("availability", {})
            if day_key in availability and availability[day_key] != "00:00-00:00":
                day_has_available_teams = True
                break

        # Skip day if no teams are available
        if not day_has_available_teams:
            current += timedelta(days=1)
            continue

        # Generate slots throughout the day at specified intervals
        # Start from midnight and go until end of day
        day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        slot = day_start
        while slot < day_end:
            total_slots_generated += 1

            for team_name, team_data in teams.items():
                # Check if team is available AND has enough time for full match
                if (AvailabilityChecker.is_team_available_for_slot(team_data, slot) and
                    AvailabilityChecker.can_fit_match(team_data, slot, MATCH_DURATION)):
                    slot_matrix[slot].add(team_name)

            # Only keep slots where at least one team is available
            if slot not in slot_matrix or len(slot_matrix[slot]) == 0:
                if slot in slot_matrix:
                    del slot_matrix[slot]
            else:
                slots_with_teams += 1

            slot += slot_interval

        current += timedelta(days=1)

    logger.info(f"[SLOT-MATRIX] Generated {slots_with_teams} usable slots (from {total_slots_generated} checked)")
    logger.info(f"[SLOT-MATRIX] Average teams per slot: {sum(len(teams) for teams in slot_matrix.values()) / max(len(slot_matrix), 1):.1f}")

    # Optional: Save JSON debug
    if DEBUG_MODE:
        try:
            os.makedirs("debug", exist_ok=True)

            debug_data = []
            for dt, teamset in sorted(slot_matrix.items()):
                debug_data.append({
                    "slot": dt.strftime("%Y-%m-%d %H:%M"),
                    "weekday": dt.strftime("%A"),
                    "team_count": len(teamset),
                    "teams": sorted(teamset),
                })

            debug_summary = {
                "total_slots_checked": total_slots_generated,
                "usable_slots": slots_with_teams,
                "slot_interval_minutes": slot_interval_minutes,
                "match_duration_minutes": int(MATCH_DURATION.total_seconds() / 60),
                "slots": debug_data
            }

            with open("debug/slot_matrix_debug.json", "w", encoding="utf-8") as f:
                json.dump(debug_summary, f, indent=2, ensure_ascii=False)

            logger.info("[SLOT-MATRIX] slot_matrix_debug.json saved.")
        except Exception as e:
            logger.warning(f"[SLOT-MATRIX] Error saving debug data: {e}")

    return dict(slot_matrix)


def get_valid_slots_for_match(team1: str, team2: str, slot_matrix: dict[datetime, set[str]]) -> list[datetime]:
    """
    Returns all slots where both team1 and team2 are available.
    """
    valid_slots = []
    for slot_time, team_set in slot_matrix.items():
        if team1 in team_set and team2 in team_set:
            valid_slots.append(slot_time)

    return sorted(valid_slots)


# =======================================
# SLOT ASSIGNMENT FUNCTIONS
# =======================================

def assign_slots_with_matrix(matches: list, slot_matrix: dict[datetime, set[str]]) -> tuple[list, list]:
    """
    Assigns slots to matches based on the global slot matrix.
    Considers pause + time budget + duplicates.
    Returns (updated_matches, unassigned_matches).
    """
    used_slots = set()
    all_slots_per_team = {}  # Changed: track ALL slots per team, not just last one
    unassigned_matches = []

    matches_with_options = []

    for match in matches:
        team1 = match["team1"]
        team2 = match["team2"]
        match_id = match["match_id"]

        valid_slots = get_valid_slots_for_match(team1, team2, slot_matrix)

        logger.debug(f"[SLOT-ASSIGN] Match {match_id} ({team1} vs {team2}): {len(valid_slots)} potential slots found")

        matches_with_options.append((match, valid_slots))

    # Matches with fewest options first
    matches_with_options.sort(key=lambda x: len(x[1]))

    for match, valid_slots in matches_with_options:
        team1 = match["team1"]
        team2 = match["team2"]
        match_id = match["match_id"]

        if len(valid_slots) == 0:
            unassigned_matches.append(match)
            logger.warning(f"[SLOT-ASSIGN] ❌ Match {match_id} ({team1} vs {team2}): No common availability slots")
            continue

        slot_found = False
        rejection_reasons = {
            "already_used": 0,
            "pause_violation": 0,
            "budget_exceeded": 0
        }

        for slot in valid_slots:
            slot_str = slot.isoformat()
            slot_date = slot.date()

            # Slot already occupied?
            if slot_str in used_slots:
                rejection_reasons["already_used"] += 1
                logger.debug(f"[SLOT-ASSIGN]   ⏭️  {slot_str}: Already occupied")
                continue

            # Respect pause rule (only check against chronologically earlier slots)
            if not is_minimum_pause_respected(all_slots_per_team, team1, team2, slot):
                rejection_reasons["pause_violation"] += 1
                continue

            # Check daily time budget
            team1_budget = get_team_time_budget(team1, slot_date, matches)
            team2_budget = get_team_time_budget(team2, slot_date, matches)

            if (
                team1_budget + MATCH_DURATION + PAUSE_DURATION > MAX_TIME_BUDGET
                or team2_budget + MATCH_DURATION + PAUSE_DURATION > MAX_TIME_BUDGET
            ):
                rejection_reasons["budget_exceeded"] += 1
                logger.debug(f"[SLOT-ASSIGN]   💰 {slot_str}: Budget exceeded ({team1}: {team1_budget}, {team2}: {team2_budget})")
                continue

            # Slot fits – assign
            match["scheduled_time"] = slot_str
            used_slots.add(slot_str)
            # Track all slots per team (not just last one)
            all_slots_per_team.setdefault(team1, []).append(slot)
            all_slots_per_team.setdefault(team2, []).append(slot)
            logger.info(f"[SLOT-ASSIGN] ✅ Match {match_id} ({team1} vs {team2}) scheduled at {slot_str}")
            slot_found = True
            break

        if not slot_found:
            unassigned_matches.append(match)
            logger.warning(f"[SLOT-ASSIGN] ❌ Match {match_id} ({team1} vs {team2}): Failed to schedule")
            logger.warning(f"[SLOT-ASSIGN]    📊 Rejection reasons: {rejection_reasons['already_used']} already used, "
                          f"{rejection_reasons['pause_violation']} pause violations, "
                          f"{rejection_reasons['budget_exceeded']} budget exceeded")

    logger.info(f"[SLOT-ASSIGN] Summary: {len(matches) - len(unassigned_matches)}/{len(matches)} matches scheduled successfully")

    return matches, unassigned_matches


def is_minimum_pause_respected(
    all_slots: dict, team1: str, team2: str, new_slot: datetime, pause_minutes: int = 30
) -> bool:
    """
    Checks if both teams had at least X minutes pause since their last match ended.
    The pause is calculated from when the previous match ended (start + duration), not just started.

    IMPORTANT: Only checks against matches that are chronologically BEFORE the new slot.
    This allows the algorithm to assign matches in any order (prioritizing difficult matches)
    without creating false pause violations when earlier slots are checked after later ones.

    :param all_slots: Dict mapping team names to lists of all their assigned slots
    :param team1: First team name
    :param team2: Second team name
    :param new_slot: The slot being considered for assignment
    :param pause_minutes: Minimum required pause in minutes (default 30)
    :return: True if pause requirement is met for both teams
    """
    for team in (team1, team2):
        team_slots = all_slots.get(team, [])

        # Only check slots that are chronologically BEFORE the new slot
        previous_slots = [slot for slot in team_slots if slot < new_slot]

        if previous_slots:
            # Find the most recent previous slot
            last_previous_slot = max(previous_slots)

            # Calculate when that match ended
            last_match_end = last_previous_slot + MATCH_DURATION

            # Calculate the actual pause time (time between match end and new slot start)
            diff = (new_slot - last_match_end).total_seconds() / 60

            if diff < pause_minutes:
                if DEBUG_MODE:
                    logger.debug(f"[PAUSE] {team} only had {diff:.0f} min pause – required: {pause_minutes} min.")
                    logger.debug(f"[PAUSE]   Last match ended: {last_match_end} | New slot: {new_slot}")
                    logger.debug(f"[PAUSE]   Timezone info - Last: {last_match_end.tzinfo} | New: {new_slot.tzinfo}")
                else:
                    logger.debug(f"[PAUSE] {team} only had {diff:.0f} min pause – required: {pause_minutes} min.")
                return False

    return True


def assign_rescue_slots(unassigned_matches, matches, slot_matrix, teams):
    """
    Tries to schedule matches from the unassigned_matches list anyway,
    by ignoring pauses and time budget.
    Marks these with 'rescue_assigned': True.
    """
    rescue_assigned = 0
    used_slots = set(m.get("scheduled_time") for m in matches if m.get("scheduled_time"))

    logger.info(f"[RESCUE] 🚨 Starting rescue mode for {len(unassigned_matches)} unscheduled matches")
    logger.info(f"[RESCUE] 🔧 Rescue mode relaxes: pause rules, time budget limits (but NOT availability)")

    for problem in unassigned_matches:
        match_id = problem["match_id"]
        team1 = problem["team1"]
        team2 = problem["team2"]

        match = next((m for m in matches if m["match_id"] == match_id), None)
        if not match:
            continue

        possible_slots = get_valid_slots_for_match(team1, team2, slot_matrix)

        if not possible_slots:
            logger.error(f"[RESCUE] ❌ Match {match_id} ({team1} vs {team2}): No common availability at all")
            logger.error(f"[RESCUE]    💡 Suggestion: Check if teams have overlapping availability windows")
            continue

        logger.debug(f"[RESCUE] 🔍 Match {match_id} ({team1} vs {team2}): {len(possible_slots)} potential slots available")

        for slot in possible_slots:
            slot_str = slot.isoformat()
            if slot_str in used_slots:
                continue  # Slot already assigned

            # Assign slot – without regard for pauses/budget
            match["scheduled_time"] = slot_str
            match["rescue_assigned"] = True
            used_slots.add(slot_str)
            rescue_assigned += 1

            logger.info(
                f"[RESCUE] ✅ Match {match_id} ({team1} vs {team2}) scheduled at {slot_str} "
                f"(⚠️  rules relaxed – may violate pause/budget)"
            )
            break

        if not match.get("scheduled_time"):
            logger.error(
                f"[RESCUE] ❌ Match {match_id} ({team1} vs {team2}): Even rescue mode failed"
            )
            logger.error(f"[RESCUE]    All {len(possible_slots)} available slots were already occupied")

    logger.info(f"[RESCUE] 📊 Rescue mode summary: {rescue_assigned}/{len(unassigned_matches)} matches rescued")

    if rescue_assigned > 0:
        logger.warning(f"[RESCUE] ⚠️  {rescue_assigned} matches scheduled with relaxed rules - check schedule carefully!")

    return matches


# =======================================
# MAIN ENTRY POINT
# =======================================

async def generate_and_assign_slots():
    """
    Main function for slot generation and match assignment.
    Uses global slot matrix and new assignment logic.

    Enhanced with automatic tournament extension when rescue mode fails due to capacity.
    """
    tournament = load_tournament_data()
    matches = tournament.get("matches", [])
    teams = tournament.get("teams", {})

    if not matches:
        logger.warning(
            "[SLOT-PLANNING] No matches found in tournament. Registration closed, but there's nothing to plan."
        )
        return

    logger.info(f"[SLOT-PLANNING] ═══════════════════════════════════════════════════")
    logger.info(f"[SLOT-PLANNING] Starting match scheduling for {len(matches)} matches and {len(teams)} teams")

    # Step 1: Generate slot matrix
    logger.info(f"[SLOT-PLANNING] Step 1/3: Generating slot matrix...")
    slot_matrix = generate_slot_matrix(tournament)

    # Step 2: Assign slots per match
    logger.info(f"[SLOT-PLANNING] Step 2/3: Assigning matches to slots (with pause & budget rules)...")
    updated_matches, unassigned_matches = assign_slots_with_matrix(matches, slot_matrix)

    # Step 3: Rescue mode for unplanned matches
    if unassigned_matches:
        logger.info(f"[SLOT-PLANNING] Step 3/3: Rescue mode for {len(unassigned_matches)} unscheduled matches...")
        updated_matches = assign_rescue_slots(unassigned_matches, updated_matches, slot_matrix, teams)
    else:
        logger.info(f"[SLOT-PLANNING] Step 3/3: Rescue mode not needed - all matches scheduled!")

    # Step 4: Auto-extend tournament if rescue mode failed due to capacity
    failed_matches = [m for m in updated_matches if not m.get("scheduled_time")]

    if failed_matches:
        logger.info(f"[SLOT-PLANNING] Step 4/4: Checking if tournament extension can help...")

        # Check which failed matches have availability overlap (capacity problem vs. no overlap)
        extendable_matches = []
        for match in failed_matches:
            team1 = match["team1"]
            team2 = match["team2"]
            potential_slots = get_valid_slots_for_match(team1, team2, slot_matrix)

            if potential_slots:
                # Teams have overlapping availability, but all slots are occupied
                extendable_matches.append(match)
                logger.info(f"[EXTEND] ✅ Match {match['match_id']} ({team1} vs {team2}) has {len(potential_slots)} potential slots (capacity issue)")
            else:
                logger.error(f"[EXTEND] ❌ Match {match['match_id']} ({team1} vs {team2}) has NO overlapping availability (unfixable)")

        if extendable_matches:
            logger.info(f"[EXTEND] 🔧 {len(extendable_matches)} matches can be fixed by extending tournament duration")

            # Extend tournament by 2 weeks
            tz = ZoneInfo(CONFIG.bot.timezone)
            tournament_end = datetime.fromisoformat(tournament["tournament_end"])
            if tournament_end.tzinfo is None:
                tournament_end = tournament_end.replace(tzinfo=tz)

            original_end = tournament_end.strftime("%Y-%m-%d")
            tournament_end += timedelta(weeks=2)
            new_end = tournament_end.strftime("%Y-%m-%d")

            tournament["tournament_end"] = tournament_end.isoformat()
            save_tournament_data(tournament)

            logger.warning(f"[EXTEND] ⏰ Tournament automatically extended: {original_end} → {new_end} (+2 weeks)")
            logger.info(f"[EXTEND] 🔄 Regenerating slot matrix with new end date...")

            # Reload tournament and regenerate slot matrix
            tournament = load_tournament_data()
            slot_matrix = generate_slot_matrix(tournament)

            # Retry failed matches with expanded slot matrix
            logger.info(f"[EXTEND] 🎯 Retrying {len(extendable_matches)} matches with expanded time window...")

            # Use rescue mode directly on extendable matches (already relaxed rules)
            updated_matches = assign_rescue_slots(extendable_matches, updated_matches, slot_matrix, teams)

            # Save updated matches
            tournament["matches"] = updated_matches
            save_tournament_data(tournament)

            # Report results
            newly_scheduled = sum(1 for m in extendable_matches if m.get("scheduled_time"))
            logger.info(f"[EXTEND] 📊 Extension result: {newly_scheduled}/{len(extendable_matches)} matches scheduled after extension")
        else:
            logger.error("[EXTEND] ❌ No matches can be fixed by extending tournament (all have no team overlap)")
    else:
        logger.info(f"[SLOT-PLANNING] Step 4/4: Extension not needed - all matches scheduled!")

    # Final summary
    scheduled_count = sum(1 for m in updated_matches if m.get("scheduled_time"))
    rescue_count = sum(1 for m in updated_matches if m.get("rescue_assigned"))
    failed_count = len(matches) - scheduled_count

    logger.info(f"[SLOT-PLANNING] ═══════════════════════════════════════════════════")
    logger.info(f"[SLOT-PLANNING] 📊 Final Statistics:")
    logger.info(f"[SLOT-PLANNING]    ✅ Successfully scheduled: {scheduled_count - rescue_count}/{len(matches)} matches")
    if rescue_count > 0:
        logger.warning(f"[SLOT-PLANNING]    ⚠️  Rescue mode used: {rescue_count} matches (may have pause/budget violations)")
    if failed_count > 0:
        logger.error(f"[SLOT-PLANNING]    ❌ Failed to schedule: {failed_count} matches (no common availability)")
    logger.info(f"[SLOT-PLANNING] ═══════════════════════════════════════════════════")

    if failed_count > 0:
        logger.error("[SLOT-PLANNING] 💡 Troubleshooting tips:")
        logger.error("[SLOT-PLANNING]    1. Check team availability windows for overlap")
        logger.error("[SLOT-PLANNING]    2. Teams with no overlap cannot be scheduled (check registration data)")
        logger.error("[SLOT-PLANNING]    3. Consider manual intervention for problematic matches")

    # Save updated matches to tournament data
    tournament["matches"] = updated_matches
    save_tournament_data(tournament)
    logger.info("[SLOT-PLANNING] 💾 Match schedule saved to tournament.json")
