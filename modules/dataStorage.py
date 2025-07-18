# modules/datastorage.py

import json
import os
import shutil
from datetime import datetime

import discord
from dotenv import load_dotenv

# lokale Modules
from modules.logger import logger

# Vars global define
_config_cache = None

# ------------------
# Konfiguration & Umgebungsvariablen
# ------------------
def load_env():
    load_dotenv()


def get_env(key, default=None):
    return os.getenv(key, default)


def to_bool(value):
    """Konvertiert 'true', '1', 'yes' zu Boolean True."""
    return str(value).lower() in ("1", "true", "yes", "on")


def get_config_bool(feature_flag: str, default: bool = False) -> bool:
    config = load_config()
    return bool(config.get("features", {}).get(feature_flag, default))


def is_debug_mode() -> bool:
    return to_bool(get_env("DEBUG", "false"))


def load_config(config_path="../configs/config.json"):
    """
    Lädt die zentrale Bot-Konfiguration aus config.json.
    Nutzt Caching, um mehrfaches Laden zu vermeiden.
    """
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    try:
        current_dir = os.path.dirname(__file__)
        full_path = os.path.join(current_dir, config_path)
        with open(full_path, "r", encoding="utf-8") as config_file:
            _config_cache = json.load(config_file)
        return _config_cache
    except FileNotFoundError:
        logger.error(f"[CONFIG] Datei nicht gefunden: {config_path}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"[CONFIG] Fehler beim Parsen von {config_path}: {e}")
        return {}


# Konfiguration laden
config = load_config()

# Load Token
TOKEN = get_env("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN fehlt in .env-Datei!")

# Debug / Feature Check
DEBUG_MODE = to_bool(get_env("DEBUG", "false"))
if not DEBUG_MODE:
    raise ValueError("DEBUG_MODE fehlt in .env-Datei!")
REMINDER_ENABLED = config.get("features", {}).get("reminder_enabled", False)
if not REMINDER_ENABLED:
    raise ValueError("REMINDER_ENABLED fehlt in config-Datei!")
try:
    RESCHEDULE_CHANNEL_ID = int(config.get("CHANNELS", {}).get("RESCHEDULE_CHANNEL_ID", "0"))
except ValueError:
    RESCHEDULE_CHANNEL_ID = 0
    logger.error("[CONFIG] RESCHEDULE_CHANNEL_ID konnte nicht als int interpretiert werden!")


# Berechne die vollständigen Pfade aus der config.json
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_FILE_PATH = os.path.join(BASE_DIR, config.get("DATA_PATH", "data/data.json"))
TOURNAMENT_FILE_PATH = os.path.join(BASE_DIR, config.get("TOURNAMENT_PATH", "data/tournament.json"))

# Standardinhalte für persistente Daten
DEFAULT_GLOBAL_DATA = {"games": [], "last_tournament_winner": {}, "player_stats": {}}

# Standardinhalte für die turnierspezifischen Daten (tournament.json)
DEFAULT_TOURNAMENT_DATA = {
    "teams": {},
    "solo": [],
    "punkte": {},
    "running": False,
    "registration_open": False,
    "poll_results": None,
}


def load_names(language="de"):
    """
    Lädt die Namen für die gewünschte Sprache aus locale/{language}/names_{language}.json.
    Gibt ein Dict zurück oder {} bei Fehler.
    """
    path = f"locale/{language}/names_{language}.json"

    if not os.path.isfile(path):
        logger.warning(f"[NAMEGEN] Sprachdatei nicht gefunden: {path}")
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"[NAMEGEN] Fehler beim Laden der Namensdatei: {e}")
        return {}

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


async def validate_permissions(guild: discord.Guild):
    """
    Prüft, ob alle in der Config angegebenen Rollen auf dem Server existieren.
    Gibt Warnungen für fehlende Rollen aus.
    """
    from modules.dataStorage import load_config
    from modules.logger import logger

    config = load_config()
    role_permissions = config.get("ROLE_PERMISSIONS", {})
    logger.info(f"[PERMISSION CHECKER] Starte Rechte-Validierung für Server '{guild.name}'...")

    for permission_group, entries in role_permissions.items():
        logger.info(f"[PERMISSION CHECKER] Gruppe '{permission_group}': Erlaubte Rollen/IDs: {entries}")
        for entry in entries:
            if entry.isdigit() and len(entry) > 10:
                logger.info(
                    f"[PERMISSION CHECKER] User-ID '{entry}' als Dev/Permission erkannt (keine Rollenprüfung notwendig)."
                )
            else:
                role = discord.utils.get(guild.roles, name=entry)
                if role:
                    logger.info(f"[PERMISSION CHECKER] Rolle '{entry}' gefunden (ID: {role.id})")
                else:
                    logger.warning(f"[PERMISSION CHECKER] ⚠️ Rolle '{entry}' NICHT im Server '{guild.name}' gefunden!")
    logger.info("[PERMISSION CHECKER] Permission-Validierung abgeschlossen.")


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
                    logger.error("⚠ Global data file format ist nicht korrekt!")
                    return {}
                return data
        except json.JSONDecodeError:
            logger.error("⚠ Global data file ist beschädigt. Leere Daten werden zurückgegeben.")
            return {}
    return {}


def save_global_data(data):
    with open(DATA_FILE_PATH, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)


def save_games(games: dict):
    try:
        current_dir = os.path.dirname(__file__)
        games_path = os.path.join(current_dir, "../data/games.json")
        with open(games_path, "w", encoding="utf-8") as file:
            json.dump({"games": games}, file, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[GAMES] Fehler beim Speichern der games.json: {e}")


def load_games() -> dict:
    """
    Lädt die Spiele als Dict aus data/games.json (Format: {"games": {...}})
    """
    try:
        current_dir = os.path.dirname(__file__)
        games_path = os.path.join(current_dir, "../data/games.json")
        with open(games_path, "r", encoding="utf-8") as file:
            games_data = json.load(file)
        return games_data.get("games", {})  # <- dict statt []
    except FileNotFoundError:
        logger.error("[GAMES] games.json nicht gefunden!")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"[GAMES] Fehler beim Parsen der games.json: {e}")
        return {}


def load_tournament_data():
    if os.path.exists(TOURNAMENT_FILE_PATH):
        try:
            with open(TOURNAMENT_FILE_PATH, "r", encoding="utf-8") as file:
                tournament = json.load(file)
                if not isinstance(tournament, dict):
                    logger.error("⚠ Tournament file format ist nicht korrekt!")
                    return DEFAULT_TOURNAMENT_DATA.copy()
                # Fehlende Schlüssel ergänzen
                for key, value in DEFAULT_TOURNAMENT_DATA.items():
                    if key not in tournament:
                        tournament[key] = value
                return tournament
        except json.JSONDecodeError:
            logger.error("⚠ Tournament file ist beschädigt. Standard-Daten werden zurückgegeben.")
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
        "poll_results": {},
    }

    with open(TOURNAMENT_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(empty_tournament, f, indent=4, ensure_ascii=False)

    logger.info(f"[RESET] Turnierdaten wurden erfolgreich zurückgesetzt.")


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
    Fügt ein Spiel zur globalen Spieleliste (games.json) hinzu.
    """
    all_games = load_games()  # gibt dict mit game_id: {...}

    if game_id in all_games:
        raise ValueError(f"Spiel-ID '{game_id}' existiert bereits.")
    if min_players_per_team > max_players_per_team:
        raise ValueError("min_players_per_team darf nicht größer sein als max_players_per_team.")

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
    logger.info(f"[GAME] Spiel '{name}' ({game_id}) erfolgreich hinzugefügt.")


def remove_game(game_id: str) -> None:
    games = load_games()
    if game_id not in games:
        raise ValueError(f"Spiel '{game_id}' wurde nicht gefunden.")

    del games[game_id]
    save_games(games)
    logger.info(f"[GAME] Spiel '{game_id}' wurde gelöscht.")


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
        "data/data.json": f"data_backup_{now}.json",
    }

    for source_file, backup_name in files_to_backup.items():
        if os.path.exists(source_file):
            shutil.copy(source_file, os.path.join(backup_folder, backup_name))
            logger.info(f"[BACKUP] Gesichert: {source_file}")
        else:
            logger.info(f"[BACKUP] Achtung: {source_file} nicht gefunden – wird übersprungen.")


def delete_tournament_file():
    """
    Löscht data/tournament.json nach Turnierende.
    """
    try:
        os.remove("data/tournament.json")
        logger.info(f"[RESET] tournament.json erfolgreich gelöscht.")
    except FileNotFoundError:
        logger.info(f"[RESET] tournament.json war nicht vorhanden.")
