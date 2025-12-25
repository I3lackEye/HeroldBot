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
from modules.dataStorage import DEBUG_MODE, load_tournament_data, save_tournament_data
from modules.embeds import send_cleanup_summary
from modules.logger import logger
from modules.utils import generate_team_name, get_active_days_config

# Helper variables
MATCH_DURATION = timedelta(minutes=90)
PAUSE_DURATION = timedelta(minutes=30)
MAX_TIME_BUDGET = timedelta(hours=2)


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


# ---------------------------------------
# Helper Functions
# ---------------------------------------
def merge_weekend_availability(avail1: dict, avail2: dict) -> dict:
    """
    Merges weekend availability of two players/teams.
    Returns the overlapping time slots for Saturday and Sunday.

    DEPRECATED: Use AvailabilityChecker.merge_availability() instead.
    """
    return AvailabilityChecker.merge_availability(avail1, avail2)


def calculate_overlap(time_range1: str, time_range2: str) -> str:
    """
    Calculates the overlap of two time ranges in format 'HH:MM-HH:MM'.

    DEPRECATED: Use AvailabilityChecker.calculate_overlap() instead.

    :param time_range1: First time range as string.
    :param time_range2: Second time range as string.
    :return: The overlapping time range as string 'HH:MM-HH:MM', or '00:00-00:00' if no overlap.
    """
    return AvailabilityChecker.calculate_overlap(time_range1, time_range2)


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

        overlap = AvailabilityChecker.merge_availability(avail1, avail2)

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
                logger.error("[MATCHMAKER] ❌ No unique team name found – Aborting.")
                break
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

    today = datetime.now().date()  # Today's date

    # Group by date
    schedule_by_day = defaultdict(list)
    for match in matches:
        scheduled_time = match.get("scheduled_time")
        if scheduled_time:
            dt = datetime.fromisoformat(scheduled_time)
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
            if match.get("rescue_assigned"):
                emoji = "❗"
            elif match_status == "completed":
                emoji = "✅"
            elif dt.date() == today:
                emoji = "🔥"
            else:
                emoji = "🕒"

            description += f"{emoji} {dt.strftime('%H:%M')} – **{team1}** vs **{team2}**\n"

        description += "\n"

    return description


async def cleanup_orphan_teams(channel: TextChannel):
    """
    Removes teams with only 1 player after registration close
    and moves them to the solo list.
    """
    tournament = load_tournament_data()
    teams = tournament.get("teams", {})
    solo = tournament.get("solo", [])

    teams_deleted = 0
    players_rescued = 0

    for team_name, team_data in list(teams.items()):
        members = team_data.get("members", [])
        if len(members) == 1:
            # Only 1 player → dissolve
            player = members[0]
            solo.append(
                {
                    "player": player,
                    "availability": team_data.get("availability", {"saturday": "00:00-23:59", "sunday": "00:00-23:59"}),
                    "unavailable_dates": team_data.get("unavailable_dates", [])
                }
            )
            del teams[team_name]
            teams_deleted += 1
            players_rescued += 1

    tournament["teams"] = teams
    tournament["solo"] = solo
    save_tournament_data(tournament)

    await send_cleanup_summary(channel, teams_deleted, players_rescued)

    logger.info(f"[CLEANUP] {teams_deleted} empty teams deleted, {players_rescued} players rescued.")


def parse_start_hour(availability_str: str) -> int:
    """
    Extracts the start hour from a time range (e.g. "12:00-20:00").
    """
    try:
        start_time = availability_str.split("-")[0]
        hour = int(start_time.split(":")[0])
        return hour
    except Exception:
        logger.warning(f"[SLOT-PLANNING] Error parsing availability: {availability_str}")
        return 10  # Default value 10 AM if something goes wrong


def team_available_on_slot(team_data, slot_datetime):
    """
    Checks if the team is allowed to play on the slot date (not blacklisted).

    DEPRECATED: Use AvailabilityChecker.is_team_available_for_slot() instead.
    """
    return not AvailabilityChecker.is_slot_blacklisted(team_data, slot_datetime)


def get_team_time_budget(team_name: str, date: datetime.date, matches: list) -> timedelta:
    """
    Calculates the total time a team is blocked on a specific day through matches + pauses.
    """
    total_time = timedelta()

    for match in matches:
        scheduled = match.get("scheduled_time")
        if not scheduled:
            continue

        try:
            match_time = datetime.fromisoformat(scheduled)
        except ValueError:
            continue

        if match_time.date() != date:
            continue

        if team_name in (match.get("team1"), match.get("team2")):
            total_time += MATCH_DURATION + PAUSE_DURATION

    return total_time


def is_team_available_at_time(team_data: dict, slot_datetime: datetime) -> bool:
    """
    Checks if a team is available at the given time.
    Respects explicit time windows in the 'availability' dict for any day.
    If a team hasn't specified availability for a day, they're considered unavailable.

    DEPRECATED: Use AvailabilityChecker.is_available_at() instead.
    """
    return AvailabilityChecker.is_available_at(team_data, slot_datetime)


def get_compatible_slots(team1: dict, team2: dict, global_slots: list) -> list:
    """
    Returns a list of slots that are within the common availability of both teams.
    Expects slot times as UTC (ISO), team availability as { "saturday": "HH:MM-HH:MM", ... }
    """
    compatible = []

    # Get team availability
    avail1 = team1.get("availability", {})
    avail2 = team2.get("availability", {})

    for slot_str in global_slots:
        try:
            slot_dt = datetime.fromisoformat(slot_str).astimezone(ZoneInfo("Europe/Berlin"))
            day = slot_dt.strftime("%A").lower()  # e.g. "saturday"
            time_str = slot_dt.strftime("%H:%M")

            # Only if day exists in both
            if day not in avail1 or day not in avail2:
                continue

            start1, end1 = avail1[day].split("-")
            start2, end2 = avail2[day].split("-")

            # Slot must be in both time ranges
            if start1 <= time_str <= end1 and start2 <= time_str <= end2:
                compatible.append(slot_str)
        except Exception as e:
            logger.warning(f"[SLOTS] Error processing slot {slot_str}: {e}")

    return compatible


# ---------------------------------------
# Main Matchmaker
# ---------------------------------------
def generate_slot_matrix(tournament: dict, slot_interval: int = 2) -> dict:
    """
    Creates a global slot matrix that indicates which teams are available at which slots.
    Returns: Dict[datetime, Set[team_name]]
    """
    from datetime import datetime, timedelta
    from collections import defaultdict

    from_date = datetime.fromisoformat(tournament["registration_end"])
    to_date = datetime.fromisoformat(tournament["tournament_end"])
    teams = tournament.get("teams", {})

    slot_matrix = defaultdict(set)

    current = from_date
    while current <= to_date:
        active_days = get_active_days_config()
        weekday = current.weekday()
        if str(weekday) not in active_days:
            current += timedelta(days=1)
            continue

        start_str = active_days[str(weekday)]["start"]
        end_str = active_days[str(weekday)]["end"]
        start_hour = int(start_str.split(":")[0])
        end_hour = int(end_str.split(":")[0])

        for hour in range(start_hour, end_hour, slot_interval):
            slot = current.replace(hour=hour, minute=0, second=0, microsecond=0)

            for team_name, team_data in teams.items():
                # Use the combined availability check from AvailabilityChecker
                if AvailabilityChecker.is_team_available_for_slot(team_data, slot):
                    slot_matrix[slot].add(team_name)

        current += timedelta(days=1)

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

            with open("debug/slot_matrix_debug.json", "w", encoding="utf-8") as f:
                json.dump(debug_data, f, indent=2, ensure_ascii=False)

            logger.info("[SLOT-MATRIX] slot_matrix_debug.json saved.")
        except Exception as e:
            logger.warning(f"[SLOT-MATRIX] Error saving: {e}")

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


def assign_slots_with_matrix(matches: list, slot_matrix: dict[datetime, set[str]]) -> tuple[list, list]:
    """
    Assigns slots to matches based on the global slot matrix.
    Considers pause + time budget + duplicates.
    Returns (updated_matches, unassigned_matches).
    """
    used_slots = set()
    last_slot_per_team = {}
    unassigned_matches = []

    matches_with_options = []

    for match in matches:
        team1 = match["team1"]
        team2 = match["team2"]
        match_id = match["match_id"]

        valid_slots = get_valid_slots_for_match(team1, team2, slot_matrix)

        matches_with_options.append((match, valid_slots))

    # Matches with fewest options first
    matches_with_options.sort(key=lambda x: len(x[1]))

    for match, valid_slots in matches_with_options:
        team1 = match["team1"]
        team2 = match["team2"]
        match_id = match["match_id"]

        for slot in valid_slots:
            slot_str = slot.isoformat()
            slot_date = slot.date()

            # Slot already occupied?
            if slot_str in used_slots:
                continue

            # Respect pause rule
            if not is_minimum_pause_respected(last_slot_per_team, team1, team2, slot):
                continue

            # Check daily time budget
            team1_budget = get_team_time_budget(team1, slot_date, matches)
            team2_budget = get_team_time_budget(team2, slot_date, matches)

            if (
                team1_budget + MATCH_DURATION + PAUSE_DURATION > MAX_TIME_BUDGET
                or team2_budget + MATCH_DURATION + PAUSE_DURATION > MAX_TIME_BUDGET
            ):
                continue

            # Slot fits – assign
            match["scheduled_time"] = slot_str
            used_slots.add(slot_str)
            last_slot_per_team[team1] = slot
            last_slot_per_team[team2] = slot
            logger.info(f"[SLOT-MATRIX] Match {match_id} scheduled at {slot_str}.")
            break

        if not match.get("scheduled_time"):
            unassigned_matches.append(match)
            logger.warning(f"[SLOT-MATRIX] No slot found for match {match_id} ({team1} vs {team2})")

    return matches, unassigned_matches


def is_minimum_pause_respected(
    last_slots: dict, team1: str, team2: str, new_slot: datetime, pause_minutes: int = 30
) -> bool:
    """
    Checks if both teams had at least X minutes pause since their last match ended.
    The pause is calculated from when the previous match ended (start + duration), not just started.
    """
    for team in (team1, team2):
        last = last_slots.get(team)
        if last:
            # Calculate when the previous match ended
            last_match_end = last + MATCH_DURATION
            # Calculate the actual pause time (time between match end and new slot start)
            diff = (new_slot - last_match_end).total_seconds() / 60
            if diff < pause_minutes:
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

    logger.info(f"[RESCUE] Starting rescue mode for {len(unassigned_matches)} matches.")

    for problem in unassigned_matches:
        match_id = problem["match_id"]
        team1 = problem["team1"]
        team2 = problem["team2"]

        match = next((m for m in matches if m["match_id"] == match_id), None)
        if not match:
            continue

        possible_slots = get_valid_slots_for_match(team1, team2, slot_matrix)
        if not possible_slots:
            logger.warning(f"[RESCUE] No common slots for match {match_id}.")
            continue

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
                f"[RESCUE] Match {match_id} ({team1} vs {team2}) scheduled at {slot_str} "
                f"(rules relaxed – rescue mode)"
            )
            break

        if not match.get("scheduled_time"):
            logger.warning(
                f"[RESCUE] Even in rescue mode no slot found for match {match_id} ({team1} vs {team2})."
            )

    logger.info(f"[RESCUE] Total {rescue_assigned} matches assigned in rescue mode.")
    return matches


# ------------------
# Main Assembly
# ------------------
async def generate_and_assign_slots():
    """
    Main function for slot generation and match assignment.
    Uses global slot matrix and new assignment logic.
    """
    tournament = load_tournament_data()
    matches = tournament.get("matches", [])
    teams = tournament.get("teams", {})

    if not matches:
        logger.warning(
            "[SLOT-PLANNING] No matches found in tournament. Registration closed, but there's nothing to plan."
        )
        return

    # Step 1: Generate slot matrix
    slot_matrix = generate_slot_matrix(tournament)

    # Step 2: Assign slots per match
    updated_matches, unassigned_matches = assign_slots_with_matrix(matches, slot_matrix)

    # Step 3: Rescue mode for unplanned matches
    updated_matches = assign_rescue_slots(unassigned_matches, updated_matches, slot_matrix, teams)

    # Save
    tournament["matches"] = updated_matches
    save_tournament_data(tournament)

    logger.info("[MATCHMAKER] Matches successfully planned via global slot matrix.")
