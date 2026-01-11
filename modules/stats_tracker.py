"""
Stats Tracker Module

Handles advanced player statistics including:
- Per-game winrates
- Head-to-head records (Nemesis/Rival)
- Win/loss streaks
- Match history tracking
- Tournament participation timeline
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from modules.dataStorage import load_global_data, save_global_data, load_tournament_data
from modules.logger import logger
from modules.config import CONFIG
from modules.embeds import load_embed_template

# Player stats directory
PLAYER_STATS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "player_stats")

# Ensure directory exists
os.makedirs(PLAYER_STATS_DIR, exist_ok=True)


def initialize_player_stats(user_id: str, mention: str = None, display_name: str = None) -> Dict:
    """
    Initialize a player's stats structure with all fields.

    :param user_id: Discord user ID
    :param mention: User mention string
    :param display_name: User display name
    :return: Initialized stats dictionary
    """
    return {
        # Basic info
        "mention": mention or f"<@{user_id}>",
        "display_name": display_name or f"Player {user_id}",

        # Tournament-level stats (existing)
        "wins": 0,
        "participations": 0,

        # Match-level stats (new)
        "match_stats": {
            "total_matches": 0,
            "match_wins": 0,
            "match_losses": 0,
        },

        # Per-game statistics (enhanced)
        "game_stats": {},

        # Head-to-head records
        "head_to_head": {},

        # Streaks
        "streaks": {
            "current": 0,
            "best_win": 0,
            "best_loss": 0,
            "current_type": None  # "win", "loss", or None
        },

        # Timeline
        "timeline": {
            "first_tournament": None,
            "last_tournament": None,
            "last_game": None
        }
    }


def load_player_stats(user_id: str) -> Optional[Dict]:
    """
    Load player statistics from individual file.

    :param user_id: Discord user ID
    :return: Player stats dictionary or None if file doesn't exist
    """
    file_path = os.path.join(PLAYER_STATS_DIR, f"{user_id}.json")

    if not os.path.exists(file_path):
        return None

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            stats = json.load(f)
        return stats
    except Exception as e:
        logger.error(f"[STATS] Error loading stats for user {user_id}: {e}")
        return None


def save_player_stats(user_id: str, stats: Dict) -> bool:
    """
    Save player statistics to individual file atomically using tempfile + rename.

    :param user_id: Discord user ID
    :param stats: Player stats dictionary
    :return: True if successful, False otherwise
    """
    import tempfile

    file_path = os.path.join(PLAYER_STATS_DIR, f"{user_id}.json")

    try:
        # Write to temporary file first (atomic operation)
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=PLAYER_STATS_DIR,
            delete=False,
            suffix='.tmp'
        ) as tmp_file:
            json.dump(stats, tmp_file, indent=2, ensure_ascii=False)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
            tmp_path = tmp_file.name

        # Atomic rename (replaces old file)
        os.replace(tmp_path, file_path)
        return True
    except Exception as e:
        logger.error(f"[STATS] Error saving stats for user {user_id}: {e}")
        # Clean up temp file if it exists
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except:
                pass
        return False


def delete_player_stats(user_id: str) -> bool:
    """
    Delete player statistics file (GDPR compliance).

    :param user_id: Discord user ID
    :return: True if deleted, False if file didn't exist or error
    """
    file_path = os.path.join(PLAYER_STATS_DIR, f"{user_id}.json")

    if not os.path.exists(file_path):
        logger.warning(f"[STATS] No stats file found for user {user_id}")
        return False

    try:
        os.remove(file_path)
        logger.info(f"[STATS] Deleted stats for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"[STATS] Error deleting stats for user {user_id}: {e}")
        return False


def list_all_players() -> List[str]:
    """
    Get list of all player IDs with stats files.

    :return: List of user IDs
    """
    try:
        # Check if directory exists before listing
        if not os.path.exists(PLAYER_STATS_DIR):
            logger.warning(f"[STATS] Player stats directory does not exist: {PLAYER_STATS_DIR}")
            os.makedirs(PLAYER_STATS_DIR, exist_ok=True)
            return []

        files = os.listdir(PLAYER_STATS_DIR)
        player_ids = [f.replace('.json', '') for f in files if f.endswith('.json')]
        return player_ids
    except PermissionError as e:
        logger.error(f"[STATS] Permission denied when accessing stats directory: {e}")
        return []
    except Exception as e:
        logger.error(f"[STATS] Error listing players: {e}")
        return []


def record_match_result(winner_ids: List[str], loser_ids: List[str], game: str,
                       winner_mentions: List[str] = None, loser_mentions: List[str] = None,
                       winner_names: List[str] = None, loser_names: List[str] = None):
    """
    Record the result of a single match and update all relevant statistics.
    Uses individual player files for storage.

    :param winner_ids: List of winner user IDs
    :param loser_ids: List of loser user IDs
    :param game: Game name
    :param winner_mentions: Optional list of winner mentions
    :param loser_mentions: Optional list of loser mentions
    :param winner_names: Optional list of winner display names
    :param loser_names: Optional list of loser display names
    """
    # Process winners
    for idx, user_id in enumerate(winner_ids):
        uid_str = str(user_id)

        # Load or initialize stats
        stats = load_player_stats(uid_str)
        if stats is None:
            mention = winner_mentions[idx] if winner_mentions and idx < len(winner_mentions) else None
            name = winner_names[idx] if winner_names and idx < len(winner_names) else None
            stats = initialize_player_stats(uid_str, mention, name)

        # Update match stats
        stats["match_stats"]["total_matches"] += 1
        stats["match_stats"]["match_wins"] += 1

        # Update per-game stats
        if game not in stats["game_stats"]:
            stats["game_stats"][game] = {
                "matches": 0,
                "wins": 0,
                "losses": 0,
                "tournaments": 0
            }
        stats["game_stats"][game]["matches"] += 1
        stats["game_stats"][game]["wins"] += 1

        # Update streaks (win)
        if stats["streaks"]["current_type"] == "win":
            stats["streaks"]["current"] += 1
        else:
            stats["streaks"]["current"] = 1
            stats["streaks"]["current_type"] = "win"

        if stats["streaks"]["current"] > stats["streaks"]["best_win"]:
            stats["streaks"]["best_win"] = stats["streaks"]["current"]

        # Update head-to-head vs losers
        for loser_id in loser_ids:
            loser_str = str(loser_id)
            if loser_str not in stats["head_to_head"]:
                stats["head_to_head"][loser_str] = {
                    "wins": 0,
                    "losses": 0,
                    "games": []
                }
            stats["head_to_head"][loser_str]["wins"] += 1
            if game not in stats["head_to_head"][loser_str]["games"]:
                stats["head_to_head"][loser_str]["games"].append(game)

        # Update timeline
        stats["timeline"]["last_game"] = game

        # Save individual player stats
        save_player_stats(uid_str, stats)

    # Process losers
    for idx, user_id in enumerate(loser_ids):
        uid_str = str(user_id)

        # Load or initialize stats
        stats = load_player_stats(uid_str)
        if stats is None:
            mention = loser_mentions[idx] if loser_mentions and idx < len(loser_mentions) else None
            name = loser_names[idx] if loser_names and idx < len(loser_names) else None
            stats = initialize_player_stats(uid_str, mention, name)

        # Update match stats
        stats["match_stats"]["total_matches"] += 1
        stats["match_stats"]["match_losses"] += 1

        # Update per-game stats
        if game not in stats["game_stats"]:
            stats["game_stats"][game] = {
                "matches": 0,
                "wins": 0,
                "losses": 0,
                "tournaments": 0
            }
        stats["game_stats"][game]["matches"] += 1
        stats["game_stats"][game]["losses"] += 1

        # Update streaks (loss)
        if stats["streaks"]["current_type"] == "loss":
            stats["streaks"]["current"] += 1
        else:
            stats["streaks"]["current"] = 1
            stats["streaks"]["current_type"] = "loss"

        if stats["streaks"]["current"] > stats["streaks"]["best_loss"]:
            stats["streaks"]["best_loss"] = stats["streaks"]["current"]

        # Update head-to-head vs winners
        for winner_id in winner_ids:
            winner_str = str(winner_id)
            if winner_str not in stats["head_to_head"]:
                stats["head_to_head"][winner_str] = {
                    "wins": 0,
                    "losses": 0,
                    "games": []
                }
            stats["head_to_head"][winner_str]["losses"] += 1
            if game not in stats["head_to_head"][winner_str]["games"]:
                stats["head_to_head"][winner_str]["games"].append(game)

        # Update timeline
        stats["timeline"]["last_game"] = game

        # Save individual player stats
        save_player_stats(uid_str, stats)

    logger.info(f"[STATS] Match result recorded: {len(winner_ids)} winners vs {len(loser_ids)} losers in {game}")


def update_tournament_participation(user_ids: List[str], game: str):
    """
    Update tournament participation stats for players.
    Called at tournament end. Uses individual player files.

    :param user_ids: List of all participant user IDs
    :param game: Game that was played
    """
    from zoneinfo import ZoneInfo
    timestamp = datetime.now(tz=ZoneInfo(CONFIG.bot.timezone)).isoformat()

    for user_id in user_ids:
        uid_str = str(user_id)

        # Load or initialize stats
        stats = load_player_stats(uid_str)
        if stats is None:
            stats = initialize_player_stats(uid_str)

        # Update participation count
        stats["participations"] += 1

        # Update game tournament count
        if game not in stats["game_stats"]:
            stats["game_stats"][game] = {
                "matches": 0,
                "wins": 0,
                "losses": 0,
                "tournaments": 0
            }
        stats["game_stats"][game]["tournaments"] += 1

        # Update timeline
        if stats["timeline"]["first_tournament"] is None:
            stats["timeline"]["first_tournament"] = timestamp
        stats["timeline"]["last_tournament"] = timestamp

        # Save individual player stats
        save_player_stats(uid_str, stats)

    logger.info(f"[STATS] Tournament participation updated for {len(user_ids)} players")


def update_tournament_wins(winner_ids: List[str]):
    """
    Update tournament wins for the tournament winners.
    Called at tournament end. Uses individual player files.

    :param winner_ids: List of winner user IDs
    """
    for user_id in winner_ids:
        uid_str = str(user_id)

        # Load or initialize stats
        stats = load_player_stats(uid_str)
        if stats is None:
            stats = initialize_player_stats(uid_str)

        # Increment tournament wins
        stats["wins"] += 1

        # Save individual player stats
        save_player_stats(uid_str, stats)

    logger.info(f"[STATS] Tournament wins updated for {len(winner_ids)} winners")


def get_nemesis(user_id: str) -> Optional[Tuple[str, Dict]]:
    """
    Find the player's nemesis (opponent with most losses against).
    Uses individual player file.

    :param user_id: User ID to check
    :return: Tuple of (opponent_id, stats_dict) or None
    """
    uid_str = str(user_id)
    stats = load_player_stats(uid_str)

    if stats is None:
        return None

    h2h = stats.get("head_to_head", {})
    if not h2h:
        return None

    # Find opponent with most losses
    nemesis = max(h2h.items(), key=lambda x: x[1]["losses"], default=None)

    if nemesis and nemesis[1]["losses"] > 0:
        return nemesis

    return None


def get_favorite_rival(user_id: str) -> Optional[Tuple[str, Dict]]:
    """
    Find the player's favorite rival (most matches played against).
    Uses individual player file.

    :param user_id: User ID to check
    :return: Tuple of (opponent_id, stats_dict) or None
    """
    uid_str = str(user_id)
    stats = load_player_stats(uid_str)

    if stats is None:
        return None

    h2h = stats.get("head_to_head", {})
    if not h2h:
        return None

    # Find opponent with most total matches
    rival = max(h2h.items(), key=lambda x: x[1]["wins"] + x[1]["losses"], default=None)

    if rival and (rival[1]["wins"] + rival[1]["losses"]) > 2:  # At least 3 matches
        return rival

    return None


def calculate_match_winrate(stats: Dict) -> float:
    """
    Calculate overall match winrate.

    :param stats: Player stats dictionary
    :return: Winrate as percentage (0-100)
    """
    match_stats = stats.get("match_stats", {})
    total = match_stats.get("total_matches", 0)

    if total == 0:
        return 0.0

    wins = match_stats.get("match_wins", 0)
    return (wins / total) * 100


def calculate_game_winrate(stats: Dict, game: str) -> float:
    """
    Calculate winrate for a specific game.

    :param stats: Player stats dictionary
    :param game: Game name
    :return: Winrate as percentage (0-100)
    """
    game_stats = stats.get("game_stats", {}).get(game, {})
    matches = game_stats.get("matches", 0)

    if matches == 0:
        return 0.0

    wins = game_stats.get("wins", 0)
    return (wins / matches) * 100


def get_top_games(stats: Dict, limit: int = 3) -> List[Tuple[str, Dict]]:
    """
    Get player's most played games.

    :param stats: Player stats dictionary
    :param limit: Number of games to return
    :return: List of (game_name, game_stats) tuples
    """
    game_stats = stats.get("game_stats", {})

    if not game_stats:
        return []

    # Sort by number of matches played
    sorted_games = sorted(game_stats.items(), key=lambda x: x[1]["matches"], reverse=True)

    return sorted_games[:limit]


def format_time_since(iso_timestamp: str, language: str = None) -> str:
    """
    Format ISO timestamp to human-readable "X days ago" with locale support.

    :param iso_timestamp: ISO format timestamp string
    :param language: Language code (en/de), defaults to CONFIG.bot.language
    :return: Human-readable string
    """
    if not language:
        language = CONFIG.bot.language

    # Load locale templates
    template = load_embed_template("player_stats", language)
    time_format = template.get("TIME_FORMAT", {})
    messages = template.get("MESSAGES", {})

    if not iso_timestamp:
        return messages.get("never", "Never")

    try:
        past = datetime.fromisoformat(iso_timestamp)
        from zoneinfo import ZoneInfo
        now = datetime.now(tz=ZoneInfo(CONFIG.bot.timezone))
        delta = now - past

        if delta.days == 0:
            if delta.seconds < 3600:
                return time_format.get("less_than_hour", "Less than an hour ago")
            hours = delta.seconds // 3600
            if hours == 1:
                template_str = time_format.get("hour_singular", "PLACEHOLDER_COUNT hour ago")
            else:
                template_str = time_format.get("hours_plural", "PLACEHOLDER_COUNT hours ago")
            return template_str.replace("PLACEHOLDER_COUNT", str(hours))
        elif delta.days == 1:
            return time_format.get("yesterday", "Yesterday")
        elif delta.days < 7:
            if delta.days == 1:
                template_str = time_format.get("day_singular", "PLACEHOLDER_COUNT day ago")
            else:
                template_str = time_format.get("days_plural", "PLACEHOLDER_COUNT days ago")
            return template_str.replace("PLACEHOLDER_COUNT", str(delta.days))
        elif delta.days < 30:
            weeks = delta.days // 7
            if weeks == 1:
                template_str = time_format.get("week_singular", "PLACEHOLDER_COUNT week ago")
            else:
                template_str = time_format.get("weeks_plural", "PLACEHOLDER_COUNT weeks ago")
            return template_str.replace("PLACEHOLDER_COUNT", str(weeks))
        elif delta.days < 365:
            months = delta.days // 30
            if months == 1:
                template_str = time_format.get("month_singular", "PLACEHOLDER_COUNT month ago")
            else:
                template_str = time_format.get("months_plural", "PLACEHOLDER_COUNT months ago")
            return template_str.replace("PLACEHOLDER_COUNT", str(months))
        else:
            years = delta.days // 365
            if years == 1:
                template_str = time_format.get("year_singular", "PLACEHOLDER_COUNT year ago")
            else:
                template_str = time_format.get("years_plural", "PLACEHOLDER_COUNT years ago")
            return template_str.replace("PLACEHOLDER_COUNT", str(years))
    except (ValueError, AttributeError):
        return messages.get("unknown", "Unknown")
