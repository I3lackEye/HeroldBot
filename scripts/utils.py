# utils.py
import discord
import re
import logging
from collections import Counter
from discord import app_commands
from datetime import datetime
from typing import List
from .logger import setup_logger
from .dataStorage import load_config, load_global_data, save_global_data, load_tournament_data

# Konfiguration laden (falls nicht schon global geladen)
config = load_config()
logger = setup_logger("logs", level=logging.INFO)

def has_permission(member: discord.Member, *required_permissions: str) -> bool:
    """
    Überprüft, ob der Member mindestens eine der in der Konfiguration
    unter den übergebenen Berechtigungen angegebenen Rollen besitzt.
    
    Beispiel: has_permission(member, "Moderator", "Admin")
    
    :param member: Der Discord Member, der den Befehl ausführt.
    :param required_permissions: Ein oder mehrere Schlüssel aus ROLE_PERMISSIONS.
    :return: True, wenn der Member mindestens eine entsprechende Rolle besitzt, sonst False.
    """
    allowed_roles = []
    role_permissions = config.get("ROLE_PERMISSIONS", {})
    for permission in required_permissions:
        allowed_roles.extend(role_permissions.get(permission, []))
    
    # Alle Rollennamen des Members abrufen:
    member_role_names = [role.name for role in member.roles]
    
    # Prüfe, ob eine der erlaubten Rollen in den Member-Rollen enthalten ist:
    return any(role in member_role_names for role in allowed_roles)

def validate_availability(zeitraum: str) -> (bool, str):
    """
    Prüft, ob der übergebene Verfügbarkeitszeitraum dem Format HH:MM-HH:MM entspricht.
    Erlaubt Zeiten von 00:00 bis 23:59.
    
    :param availability: Der Zeitbereich als String, z.B. "12:00-18:00".
    :return: (True, "") wenn valid, sonst (False, Fehlermeldung).
    """
    pattern = r"^(?:[01]?\d|2[0-3]):[0-5]\d-(?:[01]?\d|2[0-3]):[0-5]\d$"
    if not re.match(pattern, zeitraum):
        logger.info(f"Fehlerhafte Uhrzeit angegeben: {zeitraum}")
        return False, "Bitte gib die Verfügbarkeitszeit im Format HH:MM-HH:MM an (z.B. 12:00-18:00)."
    return True, ""

def validate_string(input_str: str, max_length: int = None) -> (bool, str):
    """
    Überprüft, ob der Eingabestring ausschließlich aus alphanumerischen Zeichen,
    dem Unterstrich '_', dem Bindestrich '-' und Leerzeichen besteht und optional,
    ob er höchstens max_length Zeichen lang ist.
    
    :param input_str: Der zu überprüfende String.
    :param max_length: Die maximale erlaubte Länge. Falls None, wird der Wert aus der Konfiguration (STR_MAX_LENGTH) oder 50 verwendet.
    :return: Ein Tupel (is_valid, error_message). is_valid ist True, wenn alle Prüfungen bestanden wurden,
             ansonsten False, und error_message enthält den Fehlerhinweis.
    """
    # Falls kein max_length übergeben wurde, nutze den Wert aus der Konfiguration oder 50 als Fallback.
    if max_length is None:
        max_length = config.get("STR_MAX_LENGTH", 50)
    
    # Prüfe die Länge
    if len(input_str) > max_length:
        return False, f"Die Eingabe darf höchstens {max_length} Zeichen lang sein."
    
    # Erlaubte Zeichen: alphanumerisch, '_' , '-' und Leerzeichen
    allowed_special = ['_', '-', ' ']
    invalid_chars = [char for char in input_str if not (char.isalnum() or char in allowed_special)]
    if invalid_chars:
        invalid_unique = ", ".join(sorted(set(invalid_chars)))
        return False, f"Die Eingabe enthält ungültige Zeichen: {invalid_unique}. Erlaubt sind nur Buchstaben, Zahlen, Leerzeichen, '_' und '-'."
    
    return True, ""

def get_tournament_status() -> str:
    """
    Baut den Status des Turniers als formatierten String zusammen.
    Enthalten sind: ob das Turnier läuft, ob Anmeldungen offen sind,
    welches Spiel (aus poll_results) gewählt wurde, Anzahl Teams und Solo-Spieler,
    sowie ggf. Informationen zum Spielplan.
    
    :return: String, der den aktuellen Turnierstatus beschreibt.
    """
    tournament = load_tournament_data()
    global_data = load_global_data()

    running = tournament.get("running", False)
    registration_open = tournament.get("registration_open", False)

    # Ermittlung des gewählten Spiels basierend auf poll_results
    poll_results = tournament.get("poll_results", {})
    if poll_results:
        sorted_games = sorted(poll_results.items(), key=lambda kv: kv[1], reverse=True)
        if sorted_games and sorted_games[0][1] > 0:
            chosen_game = sorted_games[0][0]
        else:
            chosen_game = "Keine Stimmen abgegeben"
    else:
        chosen_game = "Nicht ausgewählt"

    num_teams = len(tournament.get("teams", {}))
    num_solo = len(tournament.get("solo", []))
    schedule = tournament.get("schedule", [])

    status_message = (
        "**Turnierstatus**\n"
        f"Turnier läuft: {'Ja' if running else 'Nein'}\n"
        f"Anmeldungen offen: {'Ja' if registration_open else 'Nein'}\n"
        f"Gewähltes Spiel: {chosen_game}\n"
        f"Anzahl Teams: {num_teams}\n"
        f"Anzahl Solo-Spieler: {num_solo}\n"
    )
    if schedule:
        status_message += f"Anzahl Matches im Spielplan: {len(schedule)}\n"

        # Fortschritt anzeigen
        gespielt = sum(1 for match in schedule if match.get("winner"))
        offen = len(schedule) - gespielt
        status_message += f"Gespielte Matches: {gespielt}, Offen: {offen}\n"

    return status_message

def update_player_stats(winner_mentions: list[str]) -> None:
    """
    Aktualisiert in data.json unter "player_stats" den Sieg-Zähler für die angegebenen Spieler.
    :param winner_mentions: Liste von Discord-Mentions, z.B. ["<@123456789>", "<@987654321>"]
    """
    global_data = load_global_data()
    player_stats = global_data.setdefault("player_stats", {})

    for mention in winner_mentions:
        match = re.search(r"\d+", mention)
        if not match:
            logger.warning(f"Ungültige Mention: {mention}")
            continue

        user_id = match.group(0)
        user_mention = f"<@{user_id}>"

        stats = player_stats.get(user_id, {})
        stats["wins"] = stats.get("wins", 0) + 1
        stats["name"] = user_mention  # immer korrekt setzen

        player_stats[user_id] = stats

    global_data["player_stats"] = player_stats
    save_global_data(global_data)
    logger.info("Spielerstatistiken aktualisiert.")

async def remove_game_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    """
    Liefert eine Liste von app_commands.Choice, die Spiele enthalten, 
    deren Name den aktuellen Suchtext (current) beinhaltet.
    """
    data = load_global_data()
    games = data.get("games", [])
    # Filtere alle Spiele, die "current" (case-insensitive) enthalten.
    return [
        app_commands.Choice(name=game, value=game)
        for game in games if current.lower() in game.lower()
    ]

def add_manual_win(user_id: int):
    """
    Fügt einem Spieler manuell einen Sieg hinzu.
    :param user_id: Die Discord-ID des Spielers
    """
    data = load_global_data()
    player_stats = data.setdefault("player_stats", {})

    uid_str = str(user_id)
    stats = player_stats.get(uid_str, {})
    stats["wins"] = stats.get("wins", 0) + 1
    stats["name"] = f"<@{user_id}>"  # immer aktuell setzen
    player_stats[uid_str] = stats

    save_global_data(data)
    logger.info(f"[DEBUG] Manuell 1 Sieg an {stats['name']} vergeben.")

def register_participation(members: list):  # Übergib list[discord.Member]
    """
    Erhöht die Teilnahmen-Zahl für alle übergebenen Discord-Mitglieder und loggt Name + Mention.
    """
    data = load_global_data()
    player_stats = data.setdefault("player_stats", {})

    for user in members:
        uid_str = str(user.id)
        stats = player_stats.get(uid_str, {})
        stats["participations"] = stats.get("participations", 0) + 1
        stats["mention"] = user.mention
        stats["display_name"] = user.display_name
        player_stats[uid_str] = stats

        logger.info(
            f"[STATS] Teilnahme registriert für {user.display_name} ({user.mention}) – neu: {stats['participations']} Teilnahmen"
        )

    save_global_data(data)
    logger.info(f"[STATS] Teilnahmezähler für {len(members)} Spieler aktualisiert.")

def get_all_registered_user_ids(tournament: dict) -> list[int]:
    """
    Extrahiert alle Discord-User-IDs (int) aus solo-Spielern & Teams.
    """
    ids = []

    for solo_entry in tournament.get("solo", []):
        mention = solo_entry.get("player")
        if mention:
            match = re.search(r"\d+", mention)
            if match:
                ids.append(int(match.group(0)))

    for team_entry in tournament.get("teams", {}).values():
        for member in team_entry.get("members", []):
            match = re.search(r"\d+", member)
            if match:
                ids.append(int(match.group(0)))

    return ids

def update_favorite_game(user_ids: list[int], game: str):
    """
    Zählt das angegebene Spiel im Spielerprofil hoch.
    :param user_ids: Liste von Discord-User-IDs
    :param game: Der Spielname (z. B. aus tournament["game"])
    """
    data = load_global_data()
    player_stats = data.setdefault("player_stats", {})

    for uid in user_ids:
        uid_str = str(uid)
        stats = player_stats.get(uid_str, {})
        game_stats = stats.setdefault("game_stats", {})
        game_stats[game] = game_stats.get(game, 0) + 1

        # Namen sichern (falls nicht vorhanden)
        stats.setdefault("mention", f"<@{uid}>")
        stats.setdefault("display_name", f"Spieler {uid_str}")

        logger.info(f"[STATS] Spielpräferenz aktualisiert: {game} für {stats['mention']} → {game_stats[game]}x")

        player_stats[uid_str] = stats

    save_global_data(data)
    logger.info(f"[STATS] Spielstatistik aktualisiert für {len(user_ids)} Spieler.")

def finalize_tournament(winning_team: str, winners: list[int], game: str, points: int = 1):
    """
    Aktualisiert die globalen Statistiken mit Siegerinfos & Spiel.
    :param winning_team: Name des Siegerteams
    :param winners: Liste von Discord-User-IDs
    :param game: Gespieltes Spiel (z. B. aus tournament["game"])
    :param points: Standardmäßig 1 Punkt
    """
    data = load_global_data()

    # Last winner
    data["last_tournament_winner"] = {
        "winning_team": winning_team,
        "points": points,
        "game": game,
        "ended_at": datetime.now().isoformat()
    }

    # Stats erhöhen
    for uid in winners:
        uid_str = str(uid)
        stats = data.setdefault("player_stats", {}).get(uid_str, {})
        stats["wins"] = stats.get("wins", 0) + 1
        stats["mention"] = f"<@{uid}>"
        stats.setdefault("display_name", f"Spieler {uid_str}")
        data["player_stats"][uid_str] = stats
        logger.info(f"[STATS] Turniersieg für {stats['mention']} → {stats['wins']} Siege")

        # Spiel hochzählen
        game_stats = stats.setdefault("game_stats", {})
        game_stats[game] = game_stats.get(game, 0) + 1

    save_global_data(data)
    logger.info(f"[TOURNAMENT] Abschluss gespeichert für Team '{winning_team}' mit Spiel: {game}")