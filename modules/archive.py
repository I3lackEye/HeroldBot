# modules/archive.py
import json
import os
from datetime import datetime

from modules.dataStorage import (
    load_global_data,
    load_tournament_data,
    save_tournament_data,
)

# Local modules
from modules.logger import logger


def archive_current_tournament():
    """
    Archives the current tournament data to a timestamped JSON file.
    Only archives tournament-specific data (matches, teams, player_stats).

    Note: games.json is NOT archived as it rarely changes and is not tournament-specific.

    Returns the path to the archive file.
    """
    tournament = load_tournament_data()
    global_data = load_global_data()

    archive_folder = "archive"
    if not os.path.exists(archive_folder):
        os.makedirs(archive_folder)

    # Only archive tournament-relevant data from global_data
    # Exclude "games" as they're not tournament-specific and rarely change
    archive_data = {
        "archived_on": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "tournament": tournament,
        "player_stats": global_data.get("player_stats", {}),
        "last_tournament_winner": global_data.get("last_tournament_winner", {}),
    }

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = os.path.join(archive_folder, f"tournament_{timestamp}.json")

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(archive_data, f, indent=4, ensure_ascii=False)

    logger.info(f"[ARCHIVE] Tournament archived to: {filename}")
    return filename


def update_tournament_history(winner_ids: list[str], chosen_game: str, mvp_name: str = None):
    """
    Updates tournament_history.json with a new entry for the completed tournament.

    :param winner_ids: List of Discord user IDs of the winners (as strings)
    :param chosen_game: The name of the game played.
    :param mvp_name: Optional name of the MVP player.
    """
    history_path = "data/tournament_history.json"

    # Prepare file
    if not os.path.exists(history_path):
        history_data = []
    else:
        with open(history_path, "r", encoding="utf-8") as f:
            try:
                history_data = json.load(f)
            except json.JSONDecodeError:
                logger.warning("[HISTORY] tournament_history.json corrupted. Creating new file.")
                history_data = []

    # Get winner names from player stats files
    from modules.stats_tracker import load_player_stats

    winners = []
    for user_id in winner_ids:
        stats = load_player_stats(user_id)
        if stats:
            name = stats.get("display_name", f"<@{user_id}>")
        else:
            name = f"<@{user_id}>"
        winners.append(name)

    # Tournament entry
    history_entry = {
        "ended_on": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "game": chosen_game,
        "winner_ids": winner_ids,
        "winners": winners,
        "mvp": mvp_name or "Unknown",
    }

    # Append to list
    history_data.append(history_entry)

    # Save
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history_data, f, indent=4, ensure_ascii=False)

    logger.info(f"[HISTORY] Tournament completed and added to tournament_history.json: {chosen_game}.")
