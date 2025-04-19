# modules/archive.py
import os
import json
from datetime import datetime
from modules.dataStorage import load_tournament_data, load_global_data

def archive_current_tournament():
    tournament = load_tournament_data()
    global_data = load_global_data()

    archive_folder = "archive"
    if not os.path.exists(archive_folder):
        os.makedirs(archive_folder)

    archive_data = {
        "archived_on": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "tournament": tournament,
        "global_data": global_data
    }

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = os.path.join(archive_folder, f"tournament_{timestamp}.json")

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(archive_data, f, indent=4, ensure_ascii=False)

    return filename


