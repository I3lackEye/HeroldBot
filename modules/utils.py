# modules/utils.py

import random
import re
from datetime import datetime, time, timedelta
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

import discord
from discord import Embed, Interaction, app_commands

from modules.config import CONFIG
from modules.dataStorage import (
    load_games,
    load_global_data,
    load_names,
    load_tournament_data,
    save_global_data,
)

# Local modules
from modules.logger import logger


def extract_user_id(mention: str) -> Optional[int]:
    """
    Safely extracts user ID from Discord mention string.

    Handles formats: <@123>, <@!123>, @123

    :param mention: Discord mention string
    :return: User ID as int, or None if invalid format
    """
    if not mention:
        return None

    # Try regex extraction first (most robust)
    import re
    match = re.search(r'(\d{15,20})', mention)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None

    return None


def validate_user_id(user_id: str) -> bool:
    """
    Validates that a user ID string is safe for use in file paths.

    Discord user IDs are 15-20 digit numbers. This function ensures:
    - Only digits
    - Reasonable length (prevents overflow and path traversal)
    - No special characters that could cause path traversal

    :param user_id: User ID string to validate
    :return: True if valid and safe, False otherwise
    """
    if not user_id:
        return False

    # Must be purely numeric
    if not user_id.isdigit():
        return False

    # Discord IDs are 15-20 digits (Snowflake format)
    # We allow 10-25 to be safe for future-proofing
    if not (10 <= len(user_id) <= 25):
        return False

    # No path traversal characters (defense in depth)
    dangerous_chars = ['/', '\\', '..', '\0', '\n', '\r']
    if any(char in user_id for char in dangerous_chars):
        return False

    return True


def has_permission(member: discord.Member, *required_permissions: str) -> bool:
    """
    Checks if the member has at least one of the roles specified in the configuration
    under the given permissions OR is listed as a user ID in the permission list.
    """
    allowed_roles = []
    allowed_ids = set()

    # Map permission names to role lists from CONFIG
    role_map = {
        "Moderator": CONFIG.bot.roles.moderator,
        "Admin": CONFIG.bot.roles.admin,
        "Dev": CONFIG.bot.roles.dev,
    }

    for permission in required_permissions:
        role_list = role_map.get(permission, [])
        for entry in role_list:
            if entry.isdigit() and len(entry) > 10:
                allowed_ids.add(int(entry))
            else:
                allowed_roles.append(entry)

    # Get all role names of the member
    member_role_names = [role.name for role in member.roles]

    # Check for role name
    if any(role in member_role_names for role in allowed_roles):
        return True

    # Check for user ID
    if getattr(member, "id", None) in allowed_ids:
        return True

    return False


def validate_string(input_str: str, max_length: int = None) -> Tuple[bool, str]:
    """
    Checks if the input string consists only of alphanumeric characters,
    underscore '_', hyphen '-', and spaces, and optionally if it is at most max_length characters long.

    :param input_str: The string to check.
    :param max_length: The maximum allowed length. If None, the value from config (STR_MAX_LENGTH) or 50 is used.
    :return: A tuple (is_valid, error_message). is_valid is True if all checks passed,
             otherwise False, and error_message contains the error hint.
    """
    # If no max_length was passed, use the value from config or 50 as fallback
    if max_length is None:
        max_length = CONFIG.bot.max_string_length

    # Check length
    if len(input_str) > max_length:
        return False, f"Input must be at most {max_length} characters long."

    # Allowed characters: alphanumeric, '_', '-', and spaces
    allowed_special = ["_", "-", " "]
    invalid_chars = [char for char in input_str if not (char.isalnum() or char in allowed_special)]
    if invalid_chars:
        invalid_unique = ", ".join(sorted(set(invalid_chars)))
        return (
            False,
            f"Input contains invalid characters: {invalid_unique}. Only letters, numbers, spaces, '_' and '-' are allowed.",
        )

    return True, ""


def validate_time_range(time_str: str) -> Tuple[bool, str]:
    """
    Checks if a string in format HH:MM-HH:MM is a valid time range.
    """
    if not re.match(r"^\d{2}:\d{2}-\d{2}:\d{2}$", time_str):
        return False, "Invalid time format (e.g. 12:00-18:00)"
    start_str, end_str = time_str.split("-")
    try:
        start = datetime.strptime(start_str, "%H:%M")
        end = datetime.strptime(end_str, "%H:%M")
        if start >= end:
            return False, "Start time must be before end time."
    except ValueError:
        return False, "Invalid time."
    return True, ""


def validate_date(date_str: str) -> Tuple[bool, str]:
    """
    Checks if a string is a valid date in format YYYY-MM-DD.
    """
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True, ""
    except ValueError:
        return False, f"Invalid date: {date_str} (Format: YYYY-MM-DD)"


def get_tournament_status() -> str:
    """
    Builds the tournament status as a formatted string.
    Includes: whether tournament is running, whether registration is open,
    which game (from poll_results) was chosen, number of teams and solo players,
    and schedule information if available.

    :return: String describing the current tournament status.
    """
    tournament = load_tournament_data()
    global_data = load_global_data()

    running = tournament.get("running", False)
    registration_open = tournament.get("registration_open", False)

    # Determine chosen game based on poll_results
    poll_results = tournament.get("poll_results", {})
    if poll_results:
        sorted_games = sorted(poll_results.items(), key=lambda kv: kv[1], reverse=True)
        if sorted_games and sorted_games[0][1] > 0:
            chosen_game = sorted_games[0][0]
        else:
            chosen_game = "No votes cast"
    else:
        chosen_game = "Not selected"

    num_teams = len(tournament.get("teams", {}))
    num_solo = len(tournament.get("solo", []))
    schedule = tournament.get("schedule", [])

    status_message = (
        "**Tournament Status**\n"
        f"Tournament running: {'Yes' if running else 'No'}\n"
        f"Registration open: {'Yes' if registration_open else 'No'}\n"
        f"Chosen game: {chosen_game}\n"
        f"Number of teams: {num_teams}\n"
        f"Number of solo players: {num_solo}\n"
    )
    if schedule:
        status_message += f"Number of matches in schedule: {len(schedule)}\n"

        # Show progress
        played = sum(1 for match in schedule if match.get("winner"))
        open_matches = len(schedule) - played
        status_message += f"Played matches: {played}, Open: {open_matches}\n"

    return status_message


def update_player_stats(winner_mentions: list[str]) -> None:
    """
    Updates the win counter in global_data under "player_stats" for the given players.
    If a player doesn't exist yet, a new entry is created.
    """
    global_data = load_global_data()
    player_stats = global_data.setdefault("player_stats", {})

    for mention in winner_mentions:
        match = re.search(r"\d+", mention)
        if not match:
            logger.warning(f"Invalid mention: {mention}")
            continue

        user_id = match.group(0)

        # Player doesn't exist yet → create
        stats = player_stats.get(user_id)
        if stats is None:
            stats = {
                "wins": 0,
                "participations": 0,
                "mention": f"<@{user_id}>",
                "display_name": f"User {user_id}",
                "game_stats": {},
            }

        # Update statistics
        stats["wins"] += 1
        stats["participations"] += 1

        player_stats[user_id] = stats

    global_data["player_stats"] = player_stats
    save_global_data(global_data)
    logger.info("Player statistics updated.")


def add_manual_win(user_id: int) -> None:
    """
    Manually adds a win to a player.
    :param user_id: The Discord ID of the player
    """
    data = load_global_data()
    player_stats = data.setdefault("player_stats", {})

    uid_str = str(user_id)
    stats = player_stats.get(uid_str, {})
    stats["wins"] = stats.get("wins", 0) + 1
    stats["name"] = f"<@{user_id}>"  # always set current
    player_stats[uid_str] = stats

    save_global_data(data)
    logger.info(f"[DEBUG] Manually awarded 1 win to {stats['name']}.")


def register_participation(members: list) -> None:
    """
    Increases the participation count for all given Discord members and logs name + mention.
    """
    data = load_global_data()
    player_stats = data.setdefault("player_stats", {})

    for user in members:
        uid_str = str(user.id)
        stats = player_stats.get(uid_str, {})
        stats["participations"] = stats.get("participations", 0) + 1
        stats["mention"] = user.mention
        stats["display_name"] = user.display_name
        player_stats[uid_str] = stats

        logger.info(
            f"[STATS] Participation registered for {user.display_name} ({user.mention}) – new: {stats['participations']} participations"
        )

    save_global_data(data)
    logger.info(f"[STATS] Participation counter updated for {len(members)} players.")


def get_all_registered_user_ids(tournament: dict) -> list[int]:
    """
    Extracts all Discord user IDs (int) from solo players & teams.
    """
    ids = []

    for solo_entry in tournament.get("solo", []):
        mention = solo_entry.get("player")
        if mention:
            match = re.search(r"\d+", mention)
            if match:
                ids.append(int(match.group(0)))

    for team_entry in tournament.get("teams", {}).values():
        for member in team_entry.get("members", []):
            match = re.search(r"\d+", member)
            if match:
                ids.append(int(match.group(0)))

    return ids


def update_favorite_game(user_ids: list[int], game: str) -> None:
    """
    Increments the given game in the player profile.
    :param user_ids: List of Discord user IDs
    :param game: The game name (e.g. from tournament["game"])
    """
    data = load_global_data()
    player_stats = data.setdefault("player_stats", {})

    for uid in user_ids:
        uid_str = str(uid)
        stats = player_stats.get(uid_str, {})
        game_stats = stats.setdefault("game_stats", {})
        game_stats[game] = game_stats.get(game, 0) + 1

        # Save names (if not present)
        stats.setdefault("mention", f"<@{uid}>")
        stats.setdefault("display_name", f"Player {uid_str}")

        logger.info(f"[STATS] Game preference updated: {game} for {stats['mention']} → {game_stats[game]}x")

        player_stats[uid_str] = stats

    save_global_data(data)
    logger.info(f"[STATS] Game statistics updated for {len(user_ids)} players.")


def finalize_tournament(winning_team: str, winners: list[int], game: str, points: int = 1) -> None:
    """
    Updates global statistics with winner info & game.
    :param winning_team: Name of the winning team
    :param winners: List of Discord user IDs
    :param game: Game played (e.g. from tournament["game"])
    :param points: Default 1 point
    """
    data = load_global_data()

    # Last winner
    data["last_tournament_winner"] = {
        "winning_team": winning_team,
        "points": points,
        "game": game,
        "ended_at": datetime.now(tz=ZoneInfo(CONFIG.bot.timezone)).isoformat(),
    }

    # Increase stats
    for uid in winners:
        uid_str = str(uid)
        stats = data.setdefault("player_stats", {}).get(uid_str, {})
        stats["wins"] = stats.get("wins", 0) + 1
        stats["mention"] = f"<@{uid}>"
        stats.setdefault("display_name", f"Player {uid_str}")
        data["player_stats"][uid_str] = stats
        logger.info(f"[STATS] Tournament win for {stats['mention']} → {stats['wins']} wins")

        # Increment game
        game_stats = stats.setdefault("game_stats", {})
        game_stats[game] = game_stats.get(game, 0) + 1

    save_global_data(data)
    logger.info(f"[TOURNAMENT] Finalization saved for team '{winning_team}' with game: {game}")


def generate_team_name(language: str = None) -> str:
    """
    Generates a random team name from adjective and noun lists.
    If no names are found, generates a unique fallback name with UUID.

    :param language: Language (optional); default: from config
    :return: Team name as string
    """
    if not language:
        language = CONFIG.bot.language

    names = load_names(language)

    # Safety check: If file is missing or empty
    if not names or "adjectives" not in names or "nouns" not in names:
        import uuid
        # Generate unique fallback name
        unique_id = str(uuid.uuid4())[:8]
        logger.warning(f"[NAMEGEN] Names file missing or empty - using fallback name with ID {unique_id}")
        return f"Team_{unique_id}"

    adjective = random.choice(names["adjectives"])
    noun = random.choice(names["nouns"])
    return f"{adjective} {noun}"


async def smart_send(
    interaction: Interaction,
    *,
    content: str = None,
    embed: Embed = None,
    ephemeral: bool = False,
) -> None:
    """
    Sends a message via interaction.response.send_message,
    or via interaction.followup.send if already responded.
    """
    try:
        await interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)
    except discord.InteractionResponded:
        await interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)


# =======================================
# AVAILABILITY CHECKER CLASS
# =======================================
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
    def validate_availability(availability: dict) -> bool:
        """
        Validates that availability dict has properly formatted time ranges.
        Uses validate_time_range() for consistency.

        :param availability: Availability dict to validate
        :return: True if all time ranges are valid, False otherwise
        """
        if not availability:
            return False

        for day, time_range in availability.items():
            if not isinstance(time_range, str):
                logger.warning(f"[AVAILABILITY] Invalid type for {day}: {type(time_range)}")
                return False

            if time_range == "00:00-00:00":
                continue  # Empty availability is valid

            # Use existing validate_time_range from utils.py
            is_valid, error_msg = validate_time_range(time_range)
            if not is_valid:
                logger.warning(f"[AVAILABILITY] Invalid time range for {day}: {time_range} - {error_msg}")
                return False

        return True

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


def parse_availability(avail_str: str) -> tuple[time, time]:
    """
    Converts a string like '12:00-18:00' into two datetime.time objects.
    Checks if the time range is valid (at least 1 hour difference).
    """
    try:
        start_str, end_str = avail_str.split("-")
        start_time = datetime.strptime(start_str.strip(), "%H:%M").time()
        end_time = datetime.strptime(end_str.strip(), "%H:%M").time()

        # Additional logic: Start must be before end
        start_dt = datetime.combine(datetime.today(), start_time)
        end_dt = datetime.combine(datetime.today(), end_time)

        if end_dt <= start_dt:
            raise ValueError(f"End time must be after start time: '{avail_str}'")

        # Minimum duration: 1 hour
        if (end_dt - start_dt) < timedelta(hours=1):
            raise ValueError(f"Availability too short: At least 1 hour required – Input: '{avail_str}'")

        return start_time, end_time

    except Exception as e:
        logger.warning(f"[AVAILABILITY] Error parsing availability '{avail_str}': {e}")
        raise ValueError(f"Invalid availability format: {avail_str}")


def intersect_availability(avail1: str, avail2: str) -> Optional[str]:
    """
    Calculates the intersection of two time ranges in format 'HH:MM-HH:MM'.
    Returns None if there is no overlap.
    """
    try:
        start1_str, end1_str = avail1.split("-")
        start2_str, end2_str = avail2.split("-")

        start1 = datetime.strptime(start1_str, "%H:%M").time()
        end1 = datetime.strptime(end1_str, "%H:%M").time()
        start2 = datetime.strptime(start2_str, "%H:%M").time()
        end2 = datetime.strptime(end2_str, "%H:%M").time()

        latest_start = max(start1, start2)
        earliest_end = min(end1, end2)

        if latest_start >= earliest_end:
            return None  # No overlap

        return f"{latest_start.strftime('%H:%M')}-{earliest_end.strftime('%H:%M')}"
    except Exception:
        return None


def get_player_team(user_mention_or_id: str) -> Optional[str]:
    """
    Finds a player's team based on their ID or mention.

    :param user_mention_or_id: String (mention e.g. "<@123456789>" or ID "123456789")
    :return: Team name or None
    """
    tournament = load_tournament_data()

    for team_name, team_data in tournament.get("teams", {}).items():
        for member in team_data.get("members", []):
            if user_mention_or_id in member:
                return team_name
    return None


def get_team_open_matches(team_name: str) -> list:
    """
    Returns all open matches of a team.

    :param team_name: The name of the team
    :return: List of match objects
    """
    tournament = load_tournament_data()
    open_matches = []

    for match in tournament.get("matches", []):
        if match.get("status") != "completed" and (match.get("team1") == team_name or match.get("team2") == team_name):
            open_matches.append(match)

    return open_matches


async def autocomplete_players(interaction: Interaction, current: str):
    """Autocomplete function for player selection."""
    from modules.stats_tracker import list_all_players, load_player_stats

    logger.info(f"[AUTOCOMPLETE] Called – Input: {current}")
    player_ids = list_all_players()

    choices = []
    for user_id in player_ids:
        stats = load_player_stats(user_id)
        if not stats:
            continue

        member = interaction.guild.get_member(int(user_id))
        if member:
            display_name = member.display_name
        else:
            display_name = stats.get("display_name") or f"Unknown ({user_id})"

        if current.lower() in display_name.lower():
            choices.append(app_commands.Choice(name=display_name, value=user_id))

    return choices[:25]


async def autocomplete_teams(interaction: Interaction, current: str):
    """Autocomplete function for team selection."""
    logger.info(f"[AUTOCOMPLETE] Called – Input: {current}")

    tournament = load_tournament_data()
    if not tournament:
        logger.error("[AUTOCOMPLETE] No tournament data loaded!")
        return []

    teams = tournament.get("teams", {})
    if not teams:
        logger.warning("[AUTOCOMPLETE] No teams present in tournament.")
        return []

    logger.info(f"[AUTOCOMPLETE] Found teams: {list(teams.keys())}")

    # Filter teams that match the current input text
    suggestions = [
        app_commands.Choice(name=team, value=team) for team in teams.keys() if current.lower() in team.lower()
    ][:25]

    logger.info(f"[AUTOCOMPLETE] {len(suggestions)} suggestions created.")

    return suggestions


async def games_autocomplete(interaction: discord.Interaction, current: str):
    """Autocomplete function for game selection."""
    games = load_games()
    return [
        app_commands.Choice(name=cfg["name"], value=gid)
        for gid, cfg in games.items()
        if current.lower() in gid.lower() or current.lower() in cfg.get("name", "").lower()
    ][:25]  # Discord API max 25


def all_matches_completed() -> bool:
    """
    Check if all matches are completed or forfeited.
    Forfeit matches count as completed since they have a determined outcome.
    """
    tournament = load_tournament_data()
    matches = tournament.get("matches", [])

    return all(match.get("status") in ("completed", "forfeit") for match in matches)


def get_current_chosen_game() -> str:
    """
    Gets the currently chosen game from the tournament file.
    """
    tournament = load_tournament_data()
    poll_results = tournament.get("poll_results") or {}

    chosen_game = poll_results.get("chosen_game", "Unknown")
    return chosen_game


async def update_all_participants() -> None:
    """
    Increases the participation count for all tournament participants.
    """
    global_data = load_global_data()
    player_stats = global_data.setdefault("player_stats", {})

    tournament = load_tournament_data()

    # Teams
    for team_entry in tournament.get("teams", {}).values():
        for member in team_entry.get("members", []):
            match = re.search(r"\d+", member)
            if not match:
                continue
            user_id = match.group(0)
            stats = player_stats.get(user_id)
            if stats is None:
                stats = {
                    "wins": 0,
                    "participations": 0,
                    "mention": f"<@{user_id}>",
                    "display_name": f"User {user_id}",
                    "game_stats": {},
                }
            stats["participations"] += 1
            player_stats[user_id] = stats

    # Solo players
    for solo_entry in tournament.get("solo", []):
        player_str = solo_entry.get("player", "")
        match = re.search(r"\d+", player_str)
        if not match:
            continue
        user_id = match.group(0)
        stats = player_stats.get(user_id)
        if stats is None:
            stats = {
                "wins": 0,
                "participations": 0,
                "mention": f"<@{user_id}>",
                "display_name": f"User {user_id}",
                "game_stats": {},
            }
        stats["participations"] += 1
        player_stats[user_id] = stats

    global_data["player_stats"] = player_stats
    save_global_data(global_data)
    logger.info("[STATS] Participation counts updated for all participants.")


def generate_random_availability() -> dict[str, str]:
    """
    Generates random availability **only** for Saturday and Sunday.
    Each day gets a time window of 4–8 hours between 9:00 and 23:00.
    """
    special = {}

    for day in ["saturday", "sunday"]:
        start_hour = random.randint(9, 14)
        duration = random.randint(4, 8)
        end_hour = min(start_hour + duration, 23)
        special[day] = f"{start_hour:02d}:00-{end_hour:02d}:00"

    return special


def get_active_days_config() -> dict:
    """
    Gets the days on which matches can take place from tournament config.
    Returns dict with day names (e.g., 'saturday') as keys and time ranges as values.
    """
    # Return active_days from CONFIG - format: {"friday": {"start": "16:00", "end": "22:00"}, ...}
    return {
        day: {"start": day_config.start, "end": day_config.end}
        for day, day_config in CONFIG.tournament.active_days.items()
    }


def get_default_availability() -> dict:
    """
    Gets default full availability based on configured tournament days.
    Returns dict with day names as keys and "00:00-23:59" as values for each active day.

    :return: Availability dict matching active tournament days
    """
    return {
        day: "00:00-23:59"
        for day in CONFIG.tournament.active_days.keys()
    }


def calculate_optimal_tournament_duration(num_teams: int, registration_end: datetime) -> datetime:
    """
    Calculates optimal tournament end date based on number of teams and tournament configuration.

    Takes into account:
    - Number of round-robin matches: n*(n-1)/2
    - Max matches per team per day (based on time budget)
    - Active days per week from config
    - Buffer for flexibility (20% extra time)

    :param num_teams: Number of teams in the tournament
    :param registration_end: When registration ends (tournament start)
    :return: Recommended tournament end datetime
    """
    from math import ceil

    if num_teams < 2:
        # Fallback: If less than 2 teams, just use 1 week
        return registration_end + timedelta(weeks=1)

    # Calculate total number of matches (round-robin)
    total_matches = (num_teams * (num_teams - 1)) // 2

    # Calculate max matches per team per day based on time budget
    match_and_pause_minutes = CONFIG.tournament.match_duration + CONFIG.tournament.pause_duration
    max_time_budget_minutes = CONFIG.tournament.max_time_budget * 60  # Convert hours to minutes
    max_matches_per_team_per_day = int(max_time_budget_minutes / match_and_pause_minutes)

    # On a perfect day, assuming all teams can play simultaneously:
    # With n teams, we can have n/2 matches happening in parallel
    # But each team is limited to max_matches_per_team_per_day
    max_matches_per_day = min(
        (num_teams // 2) * max_matches_per_team_per_day,
        total_matches  # Can't schedule more than total matches
    )

    # Prevent division by zero
    if max_matches_per_day == 0:
        max_matches_per_day = 1

    # Calculate needed days
    days_needed = ceil(total_matches / max_matches_per_day)

    # Count active days per week
    active_days_per_week = len(CONFIG.tournament.active_days)

    # Calculate weeks needed (accounting for only active days)
    if active_days_per_week > 0:
        weeks_needed = ceil(days_needed / active_days_per_week)
    else:
        weeks_needed = ceil(days_needed / 7)  # Fallback to 7 days/week

    # Add 20% buffer for flexibility and real-world constraints
    weeks_with_buffer = ceil(weeks_needed * 1.2)

    # Minimum 1 week
    weeks_with_buffer = max(weeks_with_buffer, 1)

    tournament_end = registration_end + timedelta(weeks=weeks_with_buffer)

    logger.info(
        f"[TOURNAMENT] Auto-calculated duration: {num_teams} teams → {total_matches} matches → "
        f"{days_needed} days needed → {weeks_with_buffer} weeks (with buffer)"
    )

    return tournament_end
