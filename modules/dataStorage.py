import os
import json
import logging
from .logger import logger
from dotenv import load_dotenv
from typing import Optional
from datetime import datetime
import shutil


# Lade .env files
load_dotenv()

def load_config(config_path="../configs/config.json"):
    try:
        current_dir = os.path.dirname(__file__)
        full_path = os.path.join(current_dir, config_path)
        with open(full_path, "r", encoding="utf-8") as config_file:
            config = json.load(config_file)
        return config
    except FileNotFoundError:
        print(f"Config file '{config_path}' not found.")
        return {}
    except json.JSONDecodeError as e:
        print(f"Error parsing config file: {e}")
        return {}

# Konfiguration laden
config = load_config()

# Hole Pfade aus Umgebungsvariablen (mit Fallback auf Standardwerte)
data_path_env = os.getenv("DATA_PATH", "data/data.json")
tournament_path_env = os.getenv("TOURNAMENT_PATH", "data/tournament.json")

# Berechne die vollständigen Pfade
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

DATA_FILE_PATH = os.path.join(BASE_DIR, data_path_env)
TOURNAMENT_FILE_PATH = os.path.join(BASE_DIR, tournament_path_env)

# Standardinhalte für persistente Daten
DEFAULT_GLOBAL_DATA = {
    "games": [],
    "last_tournament_winner": {},
    "player_stats": {}
}

# Standardinhalte für die turnierspezifischen Daten (tournament.json)
DEFAULT_TOURNAMENT_DATA = {
    "teams": {},
    "solo": [],
    "punkte": {},
    "running": False,
    "registration_open": False,
    "poll_results": None,
    "schedule": []
}

# Handling der Channel Limits
channel_limit = config.get("CHANNEL_LIMIT", {})
ids = channel_limit.get("ID", [])
CHANNEL_LIMIT_1 = int(ids[0]) if ids else None

def init_file(file_path, default_content):
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(default_content, f, indent=4, ensure_ascii=False)
        logger.info(f"{file_path} erstellt")
    else:
        logger.info(f"{file_path} existiert bereits")

# Funktionen für globale Daten (data.json)
def load_global_data():
    if os.path.exists(DATA_FILE_PATH):
        try:
            with open(DATA_FILE_PATH, "r", encoding="utf-8") as file:
                data = json.load(file)
                if not isinstance(data, dict):
                    print("⚠ Global data file format ist nicht korrekt!")
                    return {}
                return data
        except json.JSONDecodeError:
            print("⚠ Global data file ist beschädigt. Leere Daten werden zurückgegeben.")
            return {}
    return {}

def save_global_data(data):
    with open(DATA_FILE_PATH, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)

# Funktionen für turnierspezifische Daten (tournament.json)
def load_tournament_data():
    if os.path.exists(TOURNAMENT_FILE_PATH):
        try:
            with open(TOURNAMENT_FILE_PATH, "r", encoding="utf-8") as file:
                tournament = json.load(file)
                if not isinstance(tournament, dict):
                    print("⚠ Tournament file format ist nicht korrekt!")
                    return DEFAULT_TOURNAMENT_DATA.copy()
                # Fehlende Schlüssel ergänzen
                for key, value in DEFAULT_TOURNAMENT_DATA.items():
                    if key not in tournament:
                        tournament[key] = value
                return tournament
        except json.JSONDecodeError:
            print("⚠ Tournament file ist beschädigt. Standard-Daten werden zurückgegeben.")
            return DEFAULT_TOURNAMENT_DATA.copy()
    return DEFAULT_TOURNAMENT_DATA.copy()

def save_tournament_data(tournament):
    with open(TOURNAMENT_FILE_PATH, "w", encoding="utf-8") as file:
        json.dump(tournament, file, indent=4, ensure_ascii=False)

def reset_tournament():
    """
    Setzt alle Turnierdaten zurück.
    Die Daten werden auf 'Startzustand' gebracht, bereit für ein neues Turnier.
    """
    empty_tournament = {
        "registration_open": False,
        "registration_end": None,
        "tournament_end": None,
        "matches": [],
        "teams": {},
        "poll_results": {}
    }

    with open("tournament.json", "w", encoding="utf-8") as f:
        json.dump(empty_tournament, f, indent=4, ensure_ascii=False)

    print("[RESET] Turnierdaten wurden erfolgreich zurückgesetzt.")

def add_game_to_data(game_title):
    """
    Fügt ein neues Spiel mit dem gegebenen Titel in die globale data.json unter "games" hinzu.
    
    :param game_title: Der Titel des Spiels als String.
    :raises ValueError: Falls der Spielname länger als die erlaubte Länge ist.
    """
    MAX_TITLE_LENGTH = config.get("STR_MAX_LENGTH")
    
    # Prüfe, ob der Spielname die maximale Länge überschreitet.
    if len(game_title) > MAX_TITLE_LENGTH:
        raise ValueError(f"Der Spielname darf maximal {MAX_TITLE_LENGTH} Zeichen lang sein.")
    
    # Lade die aktuellen globalen Daten
    data = load_global_data()
    
    # Stelle sicher, dass data ein Dictionary ist und der Schlüssel "games" existiert und eine Liste ist.
    if not isinstance(data, dict):
        data = {}
    if "games" not in data or not isinstance(data["games"], list):
        data["games"] = []
    
    # Füge den neuen Spieltitel zur "games"-Liste hinzu
    data["games"].append(game_title)
    
    # Speichere die Daten wieder ab
    save_global_data(data)
    logger.info(f"Spiel '{game_title}' wurde zu den globalen Daten hinzugefügt.")

def remove_game_from_data(game_title: str):
    """
    Entfernt ein Spiel mit dem angegebenen Titel aus der globalen data.json unter "games".
    
    :param game_title: Der Titel des zu entfernenden Spiels als String.
    :raises ValueError: Falls das Spiel nicht in der Liste enthalten ist.
    """
    # Lade die aktuellen globalen Daten
    data = load_global_data()
    
    # Prüfe, ob der Schlüssel "games" existiert und ob der Spielname darin enthalten ist
    games = data.get("games", [])
    if game_title not in games:
        raise ValueError(f"Das Spiel '{game_title}' ist nicht in der Liste enthalten.")
    
    # Entferne das Spiel aus der Liste
    games.remove(game_title)
    data["games"] = games
    # Speichere die aktualisierten Daten wieder ab
    save_global_data(data)
    logger.info(f"Spiel '{game_title}' wurde aus den globalen Daten entfernt.")

def backup_current_state():
    """
    Erstellt Backups der aktuellen Turnier- und Globaldaten aus /data/.
    Speichert sie in /backups/ mit Zeitstempel.
    """
    backup_folder = "backups"
    if not os.path.exists(backup_folder):
        os.makedirs(backup_folder)

    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    
    files_to_backup = {
        "data/tournament.json": f"tournament_backup_{now}.json",
        "data/data.json": f"data_backup_{now}.json"
    }

    for source_file, backup_name in files_to_backup.items():
        if os.path.exists(source_file):
            shutil.copy(source_file, os.path.join(backup_folder, backup_name))
            print(f"[BACKUP] Gesichert: {source_file}")
        else:
            print(f"[BACKUP] Achtung: {source_file} nicht gefunden – wird übersprungen.")

def delete_tournament_file():
    """
    Löscht data/tournament.json nach Turnierende.
    """
    try:
        os.remove("data/tournament.json")
        print("[RESET] tournament.json erfolgreich gelöscht.")
    except FileNotFoundError:
        print("[RESET] tournament.json war nicht vorhanden.")
