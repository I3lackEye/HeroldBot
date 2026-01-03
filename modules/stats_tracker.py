"""
Stats Tracker Module

Handles advanced player statistics including:
- Per-game winrates
- Head-to-head records (Nemesis/Rival)
- Win/loss streaks
- Match history tracking
- Tournament participation timeline
"""

from datetime import datetime
from typing import Dict, List, Tuple, Optional
from modules.dataStorage import load_global_data, save_global_data, load_tournament_data
from modules.logger import logger
from modules.config import CONFIG
from modules.embeds import load_embed_template


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


def record_match_result(winner_ids: List[str], loser_ids: List[str], game: str,
                       winner_mentions: List[str] = None, loser_mentions: List[str] = None,
                       winner_names: List[str] = None, loser_names: List[str] = None):
    """
    Record the result of a single match and update all relevant statistics.

    :param winner_ids: List of winner user IDs
    :param loser_ids: List of loser user IDs
    :param game: Game name
    :param winner_mentions: Optional list of winner mentions
    :param loser_mentions: Optional list of loser mentions
    :param winner_names: Optional list of winner display names
    :param loser_names: Optional list of loser display names
    """
    global_data = load_global_data()
    player_stats = global_data.setdefault("player_stats", {})

    timestamp = datetime.now().isoformat()

    # Process winners
    for idx, user_id in enumerate(winner_ids):
        uid_str = str(user_id)

        # Initialize if needed
        if uid_str not in player_stats:
            mention = winner_mentions[idx] if winner_mentions and idx < len(winner_mentions) else None
            name = winner_names[idx] if winner_names and idx < len(winner_names) else None
            player_stats[uid_str] = initialize_player_stats(uid_str, mention, name)

        stats = player_stats[uid_str]

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

    # Process losers
    for idx, user_id in enumerate(loser_ids):
        uid_str = str(user_id)

        # Initialize if needed
        if uid_str not in player_stats:
            mention = loser_mentions[idx] if loser_mentions and idx < len(loser_mentions) else None
            name = loser_names[idx] if loser_names and idx < len(loser_names) else None
            player_stats[uid_str] = initialize_player_stats(uid_str, mention, name)

        stats = player_stats[uid_str]

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

    save_global_data(global_data)
    logger.info(f"[STATS] Match result recorded: {len(winner_ids)} winners vs {len(loser_ids)} losers in {game}")


def update_tournament_participation(user_ids: List[str], game: str):
    """
    Update tournament participation stats for players.
    Called at tournament end.

    :param user_ids: List of all participant user IDs
    :param game: Game that was played
    """
    global_data = load_global_data()
    player_stats = global_data.setdefault("player_stats", {})
    timestamp = datetime.now().isoformat()

    for user_id in user_ids:
        uid_str = str(user_id)

        if uid_str not in player_stats:
            player_stats[uid_str] = initialize_player_stats(uid_str)

        stats = player_stats[uid_str]

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

    save_global_data(global_data)
    logger.info(f"[STATS] Tournament participation updated for {len(user_ids)} players")


def get_nemesis(user_id: str) -> Optional[Tuple[str, Dict]]:
    """
    Find the player's nemesis (opponent with most losses against).

    :param user_id: User ID to check
    :return: Tuple of (opponent_id, stats_dict) or None
    """
    global_data = load_global_data()
    player_stats = global_data.get("player_stats", {})

    uid_str = str(user_id)
    if uid_str not in player_stats:
        return None

    h2h = player_stats[uid_str].get("head_to_head", {})
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

    :param user_id: User ID to check
    :return: Tuple of (opponent_id, stats_dict) or None
    """
    global_data = load_global_data()
    player_stats = global_data.get("player_stats", {})

    uid_str = str(user_id)
    if uid_str not in player_stats:
        return None

    h2h = player_stats[uid_str].get("head_to_head", {})
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
        now = datetime.now()
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
