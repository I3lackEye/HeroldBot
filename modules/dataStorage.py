# modules/datastorage.py

import json
import os
import shutil
import tempfile
from datetime import datetime
from typing import Dict, Any, Optional

import discord
from dotenv import load_dotenv

# Local modules
from modules.logger import logger
from modules.config import CONFIG

# ------------------
# Environment Variables & Helper Functions
# ------------------
def load_env() -> None:
    """Load environment variables from .env file."""
    load_dotenv()


def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get environment variable value."""
    return os.getenv(key, default)


def to_bool(value: Any) -> bool:
    """Convert 'true', '1', 'yes' to Boolean True."""
    return str(value).lower() in ("1", "true", "yes", "on")


def is_debug_mode() -> bool:
    """Check if debug mode is enabled."""
    return to_bool(get_env("DEBUG", "false"))


# ------------------
# Configuration Constants
# ------------------

# Load Token
TOKEN = get_env("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN missing in .env file!")

# Debug Mode
DEBUG_MODE = is_debug_mode()

# Feature Flags (from new config system)
REMINDER_ENABLED = CONFIG.is_feature_enabled("reminder_enabled")

# Channel IDs (from new config system)
RESCHEDULE_CHANNEL_ID = CONFIG.get_channel_id("reschedule")

# Data File Paths (from new config system)
DATA_FILE_PATH = CONFIG.get_data_path("data")
TOURNAMENT_FILE_PATH = CONFIG.get_data_path("tournament")

# Base directory for calculating other paths
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GAMES_FILE_PATH = os.path.join(BASE_DIR, "data", "games.json")

# Default content for persistent data
DEFAULT_GLOBAL_DATA = {"games": [], "last_tournament_winner": {}, "player_stats": {}}

# Default content for tournament-specific data (tournament.json)
DEFAULT_TOURNAMENT_DATA = {
    "teams": {},
    "solo": [],
    "points": {},
    "running": False,
    "registration_open": False,
    "poll_results": None,
}


# ------------------
# Atomic Write Helper
# ------------------
def _atomic_write(file_path: str, data: Dict[str, Any], indent: int = 4) -> None:
    """
    Atomically write JSON data to a file.
    Writes to temp file first, then renames to avoid corruption.

    :param file_path: Target file path
    :param data: Data to write
    :param indent: JSON indentation
    """
    # Ensure directory exists
    directory = os.path.dirname(file_path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)

    # Write to temporary file first
    temp_fd, temp_path = tempfile.mkstemp(dir=directory, suffix='.tmp')
    try:
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)

        # Atomic rename (replaces original file)
        os.replace(temp_path, file_path)

    except Exception as e:
        # Clean up temp file on error
        try:
            os.unlink(temp_path)
        except:
            pass
        raise e


def load_names(language: str = "de") -> Dict[str, Any]:
    """
    Loads names for the desired language from locale/{language}/names_{language}.json.
    Returns a dict or {} on error.
    """
    path = f"locale/{language}/names_{language}.json"

    if not os.path.isfile(path):
        logger.warning(f"[NAMEGEN] Language file not found: {path}")
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"[NAMEGEN] Error loading names file: {e}")
        return {}


async def validate_channels(bot: discord.Client) -> None:
    """
    Validates that all channels specified in config exist and are accessible.
    """
    logger.info("[CHANNEL CHECKER] Starting channel validation...")

    # Get all channel names from the Channels dataclass
    channel_names = ["limits", "reminder", "reschedule"]

    for name in channel_names:
        try:
            channel_id = CONFIG.get_channel_id(name)
        except ValueError as e:
            logger.error(f"[CHANNEL CHECKER] {e}")
            continue

        if channel_id == 0:
            logger.error(f"[CHANNEL CHECKER] Channel '{name}' has invalid ID: 0")
            continue

        channel = bot.get_channel(channel_id)

        if not channel:
            logger.error(f"[CHANNEL CHECKER] Channel '{name}' with ID {channel_id} was NOT found!")
            continue

        if not isinstance(channel, discord.TextChannel):
            logger.warning(f"[CHANNEL CHECKER] Channel '{name}' (ID {channel_id}) is not a TextChannel.")

        perms = channel.permissions_for(channel.guild.me)

        if not perms.view_channel:
            logger.error(f"[CHANNEL CHECKER] Bot has NO visibility on '{name}' (ID {channel_id})!")

        if not perms.send_messages:
            logger.error(f"[CHANNEL CHECKER] Bot can NOT write in '{name}' (ID {channel_id})!")

        logger.info(f"[CHANNEL CHECKER] OK: {name} (ID {channel_id})")

    logger.info("[CHANNEL CHECKER] Channel validation completed.")


async def validate_permissions(guild: discord.Guild) -> None:
    """
    Checks if all roles specified in the config exist on the server.
    Outputs warnings for missing roles.
    """
    logger.info(f"[PERMISSION CHECKER] Starting permission validation for server '{guild.name}'...")

    # Get all role groups from CONFIG
    role_groups = {
        "Moderator": CONFIG.bot.roles.moderator,
        "Admin": CONFIG.bot.roles.admin,
        "Dev": CONFIG.bot.roles.dev,
        "Winner": CONFIG.bot.roles.winner,
    }

    for permission_group, entries in role_groups.items():
        logger.info(f"[PERMISSION CHECKER] Group '{permission_group}': Allowed roles/IDs: {entries}")
        for entry in entries:
            if entry.isdigit() and len(entry) > 10:
                logger.info(
                    f"[PERMISSION CHECKER] User ID '{entry}' recognized as Dev/Permission (no role check needed)."
                )
            else:
                role = discord.utils.get(guild.roles, name=entry)
                if role:
                    logger.info(f"[PERMISSION CHECKER] Role '{entry}' found (ID: {role.id})")
                else:
                    logger.warning(f"[PERMISSION CHECKER] ⚠️ Role '{entry}' NOT found in server '{guild.name}'!")
    logger.info("[PERMISSION CHECKER] Permission validation completed.")


def init_file(file_path: str, default_content: Dict[str, Any]) -> None:
    """
    Initialize a JSON file with default content if it doesn't exist.

    :param file_path: Path to the file
    :param default_content: Default content dictionary
    """
    if not os.path.exists(file_path):
        try:
            _atomic_write(file_path, default_content)
            logger.info(f"[INIT] Created file: {file_path}")
        except Exception as e:
            logger.error(f"[INIT] Failed to create {file_path}: {e}")
            raise
    else:
        logger.debug(f"[INIT] File already exists: {file_path}")


# Functions for global data (data.json)
def load_global_data() -> Dict[str, Any]:
    """Load global data from data.json."""
    if os.path.exists(DATA_FILE_PATH):
        try:
            with open(DATA_FILE_PATH, "r", encoding="utf-8") as file:
                data = json.load(file)
                if not isinstance(data, dict):
                    logger.error("⚠ Global data file format is incorrect!")
                    return {}
                return data
        except json.JSONDecodeError:
            logger.error("⚠ Global data file is corrupted. Returning empty data.")
            return {}
    return {}


def save_global_data(data: Dict[str, Any]) -> None:
    """
    Save global data to data.json atomically.

    :param data: Global data dictionary
    :raises ValueError: If data is not a dictionary
    :raises IOError: If write fails
    """
    if not isinstance(data, dict):
        raise ValueError("Global data must be a dictionary")

    _atomic_write(DATA_FILE_PATH, data)
    logger.debug(f"[DATA] Global data saved to {DATA_FILE_PATH}")


def save_games(games: Dict[str, Any]) -> None:
    """
    Save games dictionary to games.json atomically.

    :param games: Games dictionary
    :raises ValueError: If games is not a dictionary
    :raises IOError: If write fails
    """
    if not isinstance(games, dict):
        raise ValueError("Games data must be a dictionary")

    try:
        _atomic_write(GAMES_FILE_PATH, {"games": games}, indent=2)
        logger.debug(f"[GAMES] Games saved to {GAMES_FILE_PATH}")
    except Exception as e:
        logger.error(f"[GAMES] Error saving games.json: {e}")
        raise


def load_games() -> Dict[str, Any]:
    """
    Load games as dict from data/games.json (Format: {"games": {...}}).

    :return: Games dictionary, or empty dict on error
    """
    if not os.path.exists(GAMES_FILE_PATH):
        logger.warning(f"[GAMES] games.json not found at {GAMES_FILE_PATH}")
        return {}

    try:
        with open(GAMES_FILE_PATH, "r", encoding="utf-8") as file:
            games_data = json.load(file)

        if not isinstance(games_data, dict):
            logger.error("[GAMES] games.json format is incorrect (not a dict)")
            return {}

        return games_data.get("games", {})

    except json.JSONDecodeError as e:
        logger.error(f"[GAMES] Error parsing games.json: {e}")
        return {}
    except IOError as e:
        logger.error(f"[GAMES] Error reading games.json: {e}")
        return {}


def load_tournament_data() -> Dict[str, Any]:
    """Load tournament data from tournament.json."""
    if os.path.exists(TOURNAMENT_FILE_PATH):
        try:
            with open(TOURNAMENT_FILE_PATH, "r", encoding="utf-8") as file:
                tournament = json.load(file)
                if not isinstance(tournament, dict):
                    logger.error("⚠ Tournament file format is incorrect!")
                    return DEFAULT_TOURNAMENT_DATA.copy()
                # Add missing keys
                for key, value in DEFAULT_TOURNAMENT_DATA.items():
                    if key not in tournament:
                        tournament[key] = value
                return tournament
        except json.JSONDecodeError:
            logger.error("⚠ Tournament file is corrupted. Returning default data.")
            return DEFAULT_TOURNAMENT_DATA.copy()
    return DEFAULT_TOURNAMENT_DATA.copy()


def save_tournament_data(tournament: Dict[str, Any]) -> None:
    """
    Save tournament data to tournament.json atomically.

    :param tournament: Tournament data dictionary
    :raises ValueError: If tournament is not a dictionary
    :raises IOError: If write fails
    """
    if not isinstance(tournament, dict):
        raise ValueError("Tournament data must be a dictionary")

    _atomic_write(TOURNAMENT_FILE_PATH, tournament)
    logger.debug(f"[TOURNAMENT] Tournament data saved to {TOURNAMENT_FILE_PATH}")


def reset_tournament() -> None:
    """
    Reset all tournament data to default state.
    Uses DEFAULT_TOURNAMENT_DATA to ensure consistency.
    """
    _atomic_write(TOURNAMENT_FILE_PATH, DEFAULT_TOURNAMENT_DATA.copy())
    logger.info("[RESET] Tournament data was successfully reset to default state")


def add_game(
    game_id: str,
    *,
    name: str,
    genre: str,
    platform: str,
    match_duration_minutes: int,
    pause_minutes: int,
    min_players_per_team: int,
    max_players_per_team: int,
    visible_in_poll: bool = True,
    emoji: str = "🎮",
) -> None:
    """
    Adds a game to the global games list (games.json).
    """
    all_games = load_games()

    if game_id in all_games:
        raise ValueError(f"Game ID '{game_id}' already exists.")
    if min_players_per_team > max_players_per_team:
        raise ValueError("min_players_per_team cannot be greater than max_players_per_team.")

    all_games[game_id] = {
        "name": name,
        "genre": genre,
        "platform": platform,
        "match_duration_minutes": match_duration_minutes,
        "pause_minutes": pause_minutes,
        "min_players_per_team": min_players_per_team,
        "max_players_per_team": max_players_per_team,
        "visible_in_poll": visible_in_poll,
        "emoji": emoji,
    }

    save_games(all_games)
    logger.info(f"[GAME] Game '{name}' ({game_id}) successfully added.")


def remove_game(game_id: str) -> None:
    """Remove a game from the games list."""
    games = load_games()
    if game_id not in games:
        raise ValueError(f"Game '{game_id}' was not found.")

    del games[game_id]
    save_games(games)
    logger.info(f"[GAME] Game '{game_id}' was deleted.")


def backup_current_state() -> None:
    """
    Creates backups of tournament, global data, and games from /data/.
    Saves them in /backups/ with timestamp.
    """
    backup_folder = os.path.join(BASE_DIR, "backups")
    if not os.path.exists(backup_folder):
        os.makedirs(backup_folder)

    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    files_to_backup = {
        TOURNAMENT_FILE_PATH: f"tournament_backup_{now}.json",
        DATA_FILE_PATH: f"data_backup_{now}.json",
        GAMES_FILE_PATH: f"games_backup_{now}.json",
    }

    backed_up = 0
    for source_file, backup_name in files_to_backup.items():
        if os.path.exists(source_file):
            try:
                shutil.copy(source_file, os.path.join(backup_folder, backup_name))
                logger.info(f"[BACKUP] Backed up: {os.path.basename(source_file)}")
                backed_up += 1
            except IOError as e:
                logger.error(f"[BACKUP] Failed to backup {os.path.basename(source_file)}: {e}")
        else:
            logger.debug(f"[BACKUP] File not found, skipping: {os.path.basename(source_file)}")

    logger.info(f"[BACKUP] Backup completed: {backed_up}/{len(files_to_backup)} files backed up")


def delete_tournament_file() -> None:
    """
    Delete tournament.json file.
    Uses TOURNAMENT_FILE_PATH constant for consistency.
    """
    try:
        if os.path.exists(TOURNAMENT_FILE_PATH):
            os.remove(TOURNAMENT_FILE_PATH)
            logger.info(f"[RESET] tournament.json successfully deleted")
        else:
            logger.debug("[RESET] tournament.json was not present")
    except OSError as e:
        logger.error(f"[RESET] Failed to delete tournament.json: {e}")
