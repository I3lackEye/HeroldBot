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
from modules.task_manager import add_task, get_all_tasks
from modules.utils import (
    AvailabilityChecker,
    generate_team_name,
    get_active_days_config,
    get_default_availability,
    now_in_bot_timezone,
    ensure_timezone_aware,
    parse_iso_datetime,
    get_bot_timezone
)

# Tournament configuration (from centralized config)
MATCH_DURATION = CONFIG.tournament.match_duration
PAUSE_DURATION = CONFIG.tournament.pause_duration
MAX_TIME_BUDGET = CONFIG.tournament.max_time_budget


def _update_tournament_end_timer(new_end: datetime):
    """
    Updates the tournament end timer when the tournament is extended.
    Cancels old timer and logs the extension.

    Note: We can't reschedule the timer here because we don't have a channel reference.
    The timer will be recreated on bot restart if needed.

    :param new_end: New tournament end datetime (will be ensured timezone-aware)
    """
    # Ensure timezone-aware
    new_end = ensure_timezone_aware(new_end)

    # Cancel existing tournament_end_timer if it exists
    all_tasks = get_all_tasks()
    if "tournament_end_timer" in all_tasks:
        old_task = all_tasks["tournament_end_timer"]["task"]
        if not old_task.done():
            old_task.cancel()
            logger.info("[EXTEND] ⏰ Cancelled old tournament end timer")

    # Calculate new delay for logging
    now = now_in_bot_timezone()
    delay_seconds = max(0, int((new_end - now).total_seconds()))

    if delay_seconds > 0:
        logger.info(f"[EXTEND] ⏰ New tournament end: {new_end.strftime('%Y-%m-%d')} ({delay_seconds // 86400} days)")
        logger.info("[EXTEND] 💡 Timer will be recreated on bot restart")
    else:
        logger.warning("[EXTEND] ⚠️  New tournament end is in the past - no timer will be set")


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

        # Validate availability data
        if not AvailabilityChecker.validate_availability(avail1):
            logger.error(f"[MATCHMAKER] ❌ Invalid availability data for {name1} – Cannot create team.")
            logger.error(f"[MATCHMAKER]    💡 Please check time range format (must be HH:MM-HH:MM)")
            continue

        if not AvailabilityChecker.validate_availability(avail2):
            logger.error(f"[MATCHMAKER] ❌ Invalid availability data for {name2} – Cannot create team.")
            logger.error(f"[MATCHMAKER]    💡 Please check time range format (must be HH:MM-HH:MM)")
            continue

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

        # Generate unique team name with improved retry logic
        team_name = generate_team_name()
        attempts = 0
        max_attempts = 100  # Increased from 10 to handle larger tournaments

        while team_name in used_names or team_name in new_teams:
            team_name = generate_team_name()
            attempts += 1

            if attempts > max_attempts:
                logger.error(f"[MATCHMAKER] ❌ No unique team name found after {max_attempts} attempts – Aborting this pairing.")
                logger.error(f"[MATCHMAKER]    Players {name1} and {name2} will remain in solo queue.")
                logger.error(f"[MATCHMAKER]    💡 This may indicate too many teams with similar names ({len(used_names)} existing teams)")
                # Return players to solo queue instead of losing them
                solo_players.append(p1)
                solo_players.append(p2)
                break

            # Log periodic warnings for debugging
            if attempts % 25 == 0:
                logger.warning(f"[MATCHMAKER] ⚠️  Team name collision: {attempts} attempts so far for {name1} + {name2}")
        else:
            # Only create team if we successfully found a unique name
            used_names.add(team_name)

            new_teams[team_name] = {
                "members": [name1, name2],
                "availability": overlap,
            }

            if attempts > 0:
                logger.debug(f"[MATCHMAKER] Team name '{team_name}' found after {attempts + 1} attempts")

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

    # Get today's date in bot timezone
    today = now_in_bot_timezone().date()

    # Group by date
    schedule_by_day = defaultdict(list)
    for match in matches:
        scheduled_time = match.get("scheduled_time")
        if scheduled_time:
            dt = parse_iso_datetime(scheduled_time)
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
    total_time = timedelta()

    for match in matches:
        scheduled = match.get("scheduled_time")
        if not scheduled:
            continue

        try:
            match_time = parse_iso_datetime(scheduled)
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

def generate_slot_matrix(tournament: dict, slot_interval_minutes: int = 60, log_prefix: str = "SLOT-MATRIX") -> dict:
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

    # Parse dates and ensure they're timezone-aware
    from_date = parse_iso_datetime(tournament["registration_end"])
    to_date = parse_iso_datetime(tournament["tournament_end"])

    # Validate tournament dates
    if from_date >= to_date:
        logger.error(f"[{log_prefix}] ❌ Invalid tournament dates: registration_end ({from_date}) must be before tournament_end ({to_date})")
        logger.error(f"[{log_prefix}]    💡 Please check your tournament configuration in tournament.json")
        return {}

    teams = tournament.get("teams", {})

    if not teams:
        logger.warning(f"[{log_prefix}] No teams found, returning empty matrix.")
        return {}

    slot_matrix = defaultdict(set)
    slot_interval = timedelta(minutes=slot_interval_minutes)

    logger.info(f"[{log_prefix}] Generating slots from {from_date} to {to_date} with {slot_interval_minutes}min intervals")
    logger.info(f"[{log_prefix}] Using timezone: {CONFIG.bot.timezone}")

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

    logger.info(f"[{log_prefix}] Generated {slots_with_teams} usable slots (from {total_slots_generated} checked)")
    logger.info(f"[{log_prefix}] Average teams per slot: {sum(len(teams) for teams in slot_matrix.values()) / max(len(slot_matrix), 1):.1f}")

    # Early warning if slot matrix is empty or too small
    if len(slot_matrix) == 0:
        logger.error(f"[{log_prefix}] ❌ CRITICAL: Slot matrix is completely empty!")
        logger.error(f"[{log_prefix}]    💡 Possible causes:")

        # Diagnostic: Check if teams have any availability
        teams_with_availability = 0
        teams_without_availability = []

        for team_name, team_data in teams.items():
            availability = team_data.get("availability", {})
            if AvailabilityChecker.has_any_overlap(availability):
                teams_with_availability += 1
            else:
                teams_without_availability.append(team_name)

        if teams_with_availability == 0:
            logger.error(f"[{log_prefix}]    1. NO teams have any availability (all are 00:00-00:00)")
            logger.error(f"[{log_prefix}]       → Check team registration and availability data")
        else:
            logger.error(f"[{log_prefix}]    1. {teams_without_availability.__len__()} teams have no availability: {', '.join(teams_without_availability[:5])}")

        # Check if tournament dates are valid
        logger.error(f"[{log_prefix}]    2. Tournament date range: {from_date.date()} to {to_date.date()} ({(to_date - from_date).days} days)")
        if (to_date - from_date).days < 1:
            logger.error(f"[{log_prefix}]       → Tournament duration is too short!")

        logger.error(f"[{log_prefix}]    3. Check if team availability days match tournament active days")
        logger.error(f"[{log_prefix}]    4. Verify teams have enough time to fit matches (minimum {int(MATCH_DURATION.total_seconds() / 60)} minutes required)")

        return {}

    # Warning if slot matrix is very small
    min_slots_needed = len(tournament["matches"]) if "matches" in tournament else len(teams) * (len(teams) - 1) // 2
    if len(slot_matrix) < min_slots_needed * 0.1:  # Less than 10% of needed slots
        logger.warning(f"[{log_prefix}] ⚠️  WARNING: Only {len(slot_matrix)} slots available, but ~{min_slots_needed} matches need scheduling")
        logger.warning(f"[{log_prefix}]    This may lead to scheduling conflicts and failed match assignments")
        logger.warning(f"[{log_prefix}]    💡 Consider extending tournament duration or checking team availability windows")

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

            logger.info(f"[{log_prefix}] slot_matrix_debug.json saved.")
        except Exception as e:
            logger.warning(f"[{log_prefix}] Error saving debug data: {e}")

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
    logger.info(f"[RESCUE] 📊 Currently {len(used_slots)} slots are already occupied")

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
            logger.error(f"[RESCUE]    💡 Root cause: Teams have no overlapping time windows")

            # Provide detailed diagnostics
            team1_data = teams.get(team1, {})
            team2_data = teams.get(team2, {})
            team1_avail = team1_data.get("availability", {})
            team2_avail = team2_data.get("availability", {})

            team1_days = AvailabilityChecker.get_available_days(team1_avail)
            team2_days = AvailabilityChecker.get_available_days(team2_avail)

            logger.error(f"[RESCUE]    Team '{team1}' available on: {', '.join(team1_days) if team1_days else 'NO DAYS'}")
            logger.error(f"[RESCUE]    Team '{team2}' available on: {', '.join(team2_days) if team2_days else 'NO DAYS'}")

            common_days = set(team1_days) & set(team2_days)
            if common_days:
                logger.error(f"[RESCUE]    Common days: {', '.join(common_days)} - but no overlapping time ranges")
                for day in common_days:
                    logger.error(f"[RESCUE]      {day.capitalize()}: {team1} ({team1_avail.get(day)}) vs {team2} ({team2_avail.get(day)})")
            else:
                logger.error(f"[RESCUE]    No common days between teams - scheduling impossible")

            continue

        logger.debug(f"[RESCUE] 🔍 Match {match_id} ({team1} vs {team2}): {len(possible_slots)} potential slots available")

        # Count how many are already used
        available_count = sum(1 for slot in possible_slots if slot.isoformat() not in used_slots)
        logger.debug(f"[RESCUE]    Of which {available_count} are still free, {len(possible_slots) - available_count} already occupied")

        assigned = False
        for slot in possible_slots:
            slot_str = slot.isoformat()
            if slot_str in used_slots:
                continue  # Slot already assigned

            # Assign slot – without regard for pauses/budget
            match["scheduled_time"] = slot_str
            match["rescue_assigned"] = True
            used_slots.add(slot_str)
            rescue_assigned += 1
            assigned = True

            logger.info(
                f"[RESCUE] ✅ Match {match_id} ({team1} vs {team2}) scheduled at {slot_str} "
                f"(⚠️  rules relaxed – may violate pause/budget)"
            )
            break

        if not assigned:
            logger.error(f"[RESCUE] ❌ Match {match_id} ({team1} vs {team2}): Even rescue mode failed")
            logger.error(f"[RESCUE]    All {len(possible_slots)} potentially available slots were already occupied by other matches")

            # Show time distribution of occupied slots
            slot_dates = defaultdict(int)
            for slot in possible_slots:
                if slot.isoformat() in used_slots:
                    slot_dates[slot.date()] += 1

            if slot_dates:
                logger.error(f"[RESCUE]    Occupied slot distribution by date:")
                for date, count in sorted(slot_dates.items())[:5]:  # Show first 5 dates
                    logger.error(f"[RESCUE]      {date}: {count} slots occupied")
                if len(slot_dates) > 5:
                    logger.error(f"[RESCUE]      ... and {len(slot_dates) - 5} more dates")

            logger.error(f"[RESCUE]    💡 Solution: Extend tournament duration or reduce team count")

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

        # Retry extension up to 3 times
        max_extension_attempts = 3
        extension_weeks_per_attempt = 2
        total_newly_scheduled = 0

        for attempt in range(1, max_extension_attempts + 1):
            # Get current failed matches
            current_failed = [m for m in updated_matches if not m.get("scheduled_time")]

            if not current_failed:
                logger.info(f"[EXTEND] ✅ All matches scheduled after {attempt - 1} extension(s)!")
                break

            logger.info(f"[EXTEND] 🔄 Extension attempt {attempt}/{max_extension_attempts} for {len(current_failed)} unscheduled matches")

            # Check which failed matches have availability overlap (capacity problem vs. no overlap)
            extendable_matches = []
            unfixable_matches = []

            for match in current_failed:
                team1 = match["team1"]
                team2 = match["team2"]
                potential_slots = get_valid_slots_for_match(team1, team2, slot_matrix)

                if potential_slots:
                    # Teams have overlapping availability, but all slots are occupied
                    extendable_matches.append(match)
                    logger.debug(f"[EXTEND] ✅ Match {match['match_id']} ({team1} vs {team2}) has {len(potential_slots)} potential slots (capacity issue)")
                else:
                    unfixable_matches.append(match)
                    if attempt == 1:  # Only log on first attempt to avoid spam
                        logger.error(f"[EXTEND] ❌ Match {match['match_id']} ({team1} vs {team2}) has NO overlapping availability (unfixable by extension)")

            if not extendable_matches:
                logger.warning(f"[EXTEND] ⚠️  No matches can be fixed by extension (all have no team overlap)")
                logger.warning(f"[EXTEND]    {len(unfixable_matches)} matches remain unfixable due to no overlapping availability")
                break

            logger.info(f"[EXTEND] 🔧 {len(extendable_matches)} matches might be fixable by extending tournament duration")

            # Extend tournament by configured weeks
            tournament_end = parse_iso_datetime(tournament["tournament_end"])

            original_end = tournament_end.strftime("%Y-%m-%d")
            tournament_end += timedelta(weeks=extension_weeks_per_attempt)
            new_end = tournament_end.strftime("%Y-%m-%d")

            tournament["tournament_end"] = tournament_end.isoformat()
            save_tournament_data(tournament)

            logger.warning(f"[EXTEND] ⏰ Tournament automatically extended: {original_end} → {new_end} (+{extension_weeks_per_attempt} weeks)")

            # Update tournament end timer task
            _update_tournament_end_timer(tournament_end)

            logger.info(f"[EXTEND] 🔄 Regenerating slot matrix with new end date...")

            # Reload tournament and regenerate slot matrix
            tournament = load_tournament_data()
            slot_matrix = generate_slot_matrix(tournament, log_prefix="EXTEND-MATRIX")

            # Retry failed matches with expanded slot matrix
            logger.info(f"[EXTEND] 🎯 Retrying {len(extendable_matches)} matches with expanded time window...")

            # Use rescue mode directly on extendable matches (already relaxed rules)
            updated_matches = assign_rescue_slots(extendable_matches, updated_matches, slot_matrix, teams)

            # Count newly scheduled matches in this attempt
            newly_scheduled_this_attempt = sum(1 for m in extendable_matches if m.get("scheduled_time"))
            total_newly_scheduled += newly_scheduled_this_attempt

            logger.info(f"[EXTEND] 📊 Attempt {attempt} result: {newly_scheduled_this_attempt}/{len(extendable_matches)} matches scheduled")

            # Check if we made progress
            if newly_scheduled_this_attempt == 0:
                logger.warning(f"[EXTEND] ⚠️  No progress made in attempt {attempt} - stopping extension attempts")
                logger.warning(f"[EXTEND]    Remaining {len(extendable_matches)} matches may require manual intervention")
                break

            # Save progress after each attempt
            tournament["matches"] = updated_matches
            save_tournament_data(tournament)

        # Final extension summary
        still_failed = [m for m in updated_matches if not m.get("scheduled_time")]
        if total_newly_scheduled > 0:
            logger.info(f"[EXTEND] 🎉 Extension complete: {total_newly_scheduled} additional matches scheduled")
        if still_failed:
            logger.error(f"[EXTEND] ⚠️  {len(still_failed)} matches could not be scheduled even after extension")
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
