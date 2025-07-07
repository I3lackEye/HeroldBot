# modules/archive.py
import os
import json
from datetime import datetime

# Lokale Module
from modules.logger import logger
from modules.dataStorage import (
    load_tournament_data,
    save_tournament_data,
    load_global_data,
)


def archive_current_tournament():
    tournament = load_tournament_data()
    global_data = load_global_data()

    archive_folder = "archive"
    if not os.path.exists(archive_folder):
        os.makedirs(archive_folder)

    archive_data = {
        "archived_on": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "tournament": tournament,
        "global_data": global_data,
    }

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = os.path.join(archive_folder, f"tournament_{timestamp}.json")

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(archive_data, f, indent=4, ensure_ascii=False)

    return filename


def update_tournament_history(
    winner_ids: list[str], chosen_game: str, mvp_name: str = None
):
    """
    Aktualisiert die tournament_history.json mit einem neuen Eintrag für das beendete Turnier.

    :param winner_ids: Liste der Discord-User-IDs der Gewinner (als Strings)
    :param chosen_game: Der Name des gespielten Spiels.
    :param mvp_name: Optionaler Name des MVP-Spielers.
    """
    history_path = "data/tournament_history.json"

    # Datei vorbereiten
    if not os.path.exists(history_path):
        history_data = []
    else:
        with open(history_path, "r", encoding="utf-8") as f:
            try:
                history_data = json.load(f)
            except json.JSONDecodeError:
                logger.warning(
                    "[HISTORY] tournament_history.json beschädigt. Erstelle neue Datei."
                )
                history_data = []

    # Gewinnernamen aus global_data holen
    global_data = load_global_data()
    player_stats = global_data.get("player_stats", {})

    winners = []
    for user_id in winner_ids:
        name = player_stats.get(user_id, {}).get("name", f"<@{user_id}>")
        winners.append(name)

    # Turnier-Entry
    history_entry = {
        "ended_on": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "game": chosen_game,
        "winner_ids": winner_ids,
        "winners": winners,
        "mvp": mvp_name or "Unbekannt",
    }

    # An Liste anhängen
    history_data.append(history_entry)

    # Speichern
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history_data, f, indent=4, ensure_ascii=False)

    logger.info(
        f"[HISTORY] Turnier abgeschlossen und in tournament_history.json eingetragen: {chosen_game}."
    )
