import os
import json
import logging
from .logger import logger
from dotenv import load_dotenv
from typing import Optional
from datetime import datetime
import discord
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

def load_games() -> list:
    """
    Lädt die Liste aller verfügbaren Spiele aus data/games.json.
    """
    try:
        current_dir = os.path.dirname(__file__)
        games_path = os.path.join(current_dir, "../data/games.json")
        with open(games_path, "r", encoding="utf-8") as file:
            games_data = json.load(file)
        return games_data.get("games", [])
    except FileNotFoundError:
        logger.error("[GAMES] games.json nicht gefunden!")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"[GAMES] Fehler beim Parsen der games.json: {e}")
        return []

def load_names(language="de"):
    path = f"configs/names_{language}.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

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
    "poll_results": None
}

async def validate_channels(bot: discord.Client):
    config = load_config()
    channels = config.get("CHANNELS", {})
    
    if not channels:
        logger.error("[CHANNEL CHECKER] Keine CHANNELS in der Config gefunden.")
        return

    logger.info("[CHANNEL CHECKER] Starte Channel-Validierung...")

    for name, channel_id_str in channels.items():
        try:
            channel_id = int(channel_id_str)
        except (TypeError, ValueError):
            logger.error(f"[CHANNEL CHECKER] Channel-ID für '{name}' ist ungültig: {channel_id_str}")
            continue

        channel = bot.get_channel(channel_id)

        if not channel:
            logger.error(f"[CHANNEL CHECKER] Channel '{name}' mit ID {channel_id} wurde NICHT gefunden!")
            continue

        if not isinstance(channel, discord.TextChannel):
            logger.warning(f"[CHANNEL CHECKER] Channel '{name}' (ID {channel_id}) ist kein TextChannel.")

        perms = channel.permissions_for(channel.guild.me)

        if not perms.view_channel:
            logger.error(f"[CHANNEL CHECKER] Bot hat KEINE Sichtbarkeit auf '{name}' (ID {channel_id})!")

        if not perms.send_messages:
            logger.error(f"[CHANNEL CHECKER] Bot kann NICHT in '{name}' schreiben (ID {channel_id})!")

        logger.info(f"[CHANNEL CHECKER] OK: {name} (ID {channel_id})")

    logger.info("[CHANNEL CHECKER] Channel-Validierung abgeschlossen.")

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

def save_games(games: list):
    """
    Speichert die Spieleliste in data/games.json.
    """
    try:
        current_dir = os.path.dirname(__file__)
        games_path = os.path.join(current_dir, "../data/games.json")
        with open(games_path, "w", encoding="utf-8") as file:
            json.dump({"games": games}, file, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[GAMES] Fehler beim Speichern der games.json: {e}")

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

def add_game(game_title: str):
    """
    Fügt ein neues Spiel in data/games.json hinzu.

    :param game_title: Der Titel des Spiels als String.
    :raises ValueError: Falls der Spielname länger als die erlaubte Länge ist.
    """
    MAX_TITLE_LENGTH = config.get("STR_MAX_LENGTH", 100)  # fallback falls config fehlt

    if len(game_title) > MAX_TITLE_LENGTH:
        raise ValueError(f"Der Spielname darf maximal {MAX_TITLE_LENGTH} Zeichen lang sein.")
    
    games = load_games()

    if game_title in games:
        logger.warning(f"[GAMES] Das Spiel '{game_title}' existiert bereits.")
        return

    games.append(game_title)
    save_games(games)
    logger.info(f"[GAMES] Spiel '{game_title}' erfolgreich gespeichert.")

def remove_game(game_title: str):
    """
    Entfernt ein Spiel aus data/games.json.

    :param game_title: Der Titel des Spiels, das entfernt werden soll.
    """
    games = load_games()

    if game_title not in games:
        logger.warning(f"[GAMES] Das Spiel '{game_title}' wurde nicht gefunden.")
        return

    games.remove(game_title)
    save_games(games)
    logger.info(f"[GAMES] Spiel '{game_title}' erfolgreich entfernt.")

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
