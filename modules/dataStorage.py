# modules/datastorage.py

import json
import os
import shutil
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
    """Initialize a file with default content if it doesn't exist."""
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(default_content, f, indent=4, ensure_ascii=False)
        logger.info(f"{file_path} created")
    else:
        logger.info(f"{file_path} already exists")


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
    """Save global data to data.json."""
    with open(DATA_FILE_PATH, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)


def save_games(games: Dict[str, Any]) -> None:
    """Save games dictionary to games.json."""
    try:
        current_dir = os.path.dirname(__file__)
        games_path = os.path.join(current_dir, "../data/games.json")
        with open(games_path, "w", encoding="utf-8") as file:
            json.dump({"games": games}, file, indent=2, ensure_ascii=False)
    except (IOError, TypeError) as e:
        logger.error(f"[GAMES] Error saving games.json: {e}")


def load_games() -> Dict[str, Any]:
    """
    Loads games as dict from data/games.json (Format: {"games": {...}})
    """
    try:
        current_dir = os.path.dirname(__file__)
        games_path = os.path.join(current_dir, "../data/games.json")
        with open(games_path, "r", encoding="utf-8") as file:
            games_data = json.load(file)
        return games_data.get("games", {})
    except FileNotFoundError:
        logger.error("[GAMES] games.json not found!")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"[GAMES] Error parsing games.json: {e}")
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
    """Save tournament data to tournament.json."""
    with open(TOURNAMENT_FILE_PATH, "w", encoding="utf-8") as file:
        json.dump(tournament, file, indent=4, ensure_ascii=False)


def reset_tournament() -> None:
    """
    Resets all tournament data.
    The data is brought to 'initial state', ready for a new tournament.
    """
    empty_tournament = {
        "registration_open": False,
        "registration_end": None,
        "tournament_end": None,
        "matches": [],
        "teams": {},
        "poll_results": {},
    }

    with open(TOURNAMENT_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(empty_tournament, f, indent=4, ensure_ascii=False)

    logger.info(f"[RESET] Tournament data was successfully reset.")


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
    Creates backups of the current tournament and global data from /data/.
    Saves them in /backups/ with timestamp.
    """
    backup_folder = "backups"
    if not os.path.exists(backup_folder):
        os.makedirs(backup_folder)

    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    files_to_backup = {
        "data/tournament.json": f"tournament_backup_{now}.json",
        "data/data.json": f"data_backup_{now}.json",
    }

    for source_file, backup_name in files_to_backup.items():
        if os.path.exists(source_file):
            shutil.copy(source_file, os.path.join(backup_folder, backup_name))
            logger.info(f"[BACKUP] Backed up: {source_file}")
        else:
            logger.info(f"[BACKUP] Warning: {source_file} not found – skipping.")


def delete_tournament_file() -> None:
    """
    Deletes data/tournament.json after tournament end.
    """
    try:
        os.remove("data/tournament.json")
        logger.info(f"[RESET] tournament.json successfully deleted.")
    except FileNotFoundError:
        logger.info(f"[RESET] tournament.json was not present.")
