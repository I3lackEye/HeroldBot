# modules/utils.py

import discord
import re
import logging
import random
import time

from collections import Counter
from random import randint, choice
from discord import app_commands, Interaction, Embed
from datetime import datetime, timedelta
from typing import List
from typing import Optional
from discord.app_commands import Choice

# Lokale Module
from modules.logger import logger
from modules.dataStorage import load_config, load_global_data, save_global_data, load_tournament_data, load_games, load_names

# Konfiguration laden
config = load_config()

def has_permission(member: discord.Member, *required_permissions: str) -> bool:
    """
    Überprüft, ob der Member mindestens eine der in der Konfiguration
    unter den übergebenen Berechtigungen angegebenen Rollen besitzt ODER als User-ID in der Permission-Liste steht.
    """
    allowed_roles = []
    allowed_ids = set()
    role_permissions = config.get("ROLE_PERMISSIONS", {})
    for permission in required_permissions:
        for entry in role_permissions.get(permission, []):
            if entry.isdigit() and len(entry) > 10:
                allowed_ids.add(int(entry))
            else:
                allowed_roles.append(entry)

    # Alle Rollennamen des Members abrufen:
    member_role_names = [role.name for role in member.roles]

    # Prüfe auf Rollenname
    if any(role in member_role_names for role in allowed_roles):
        return True

    # Prüfe auf User-ID
    if getattr(member, "id", None) in allowed_ids:
        return True

    return False

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

def validate_time_range(time_str):
    """
    Prüft, ob ein String im Format HH:MM-HH:MM eine echte Uhrzeitspanne ist.
    """
    if not re.match(r"^\d{2}:\d{2}-\d{2}:\d{2}$", time_str):
        return False, "Ungültiges Zeitformat (z.B. 12:00-18:00)"
    start_str, end_str = time_str.split('-')
    try:
        start = datetime.strptime(start_str, "%H:%M")
        end = datetime.strptime(end_str, "%H:%M")
        if start >= end:
            return False, "Die Startzeit muss vor der Endzeit liegen."
        # Normalerweise sollte strptime die Zeitbereiche schon abdecken. Better safe than sorry!
    except ValueError:
        return False, "Ungültige Uhrzeit."
    return True, ""

def validate_date(date_str):
    """
    Prüft, ob ein String ein echtes Datum im Format YYYY-MM-DD ist.
    """
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True, ""
    except ValueError:
        return False, f"Ungültiges Datum: {date_str} (Format: YYYY-MM-DD)"

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
    Aktualisiert in global_data unter "player_stats" den Sieg-Zähler für die angegebenen Spieler.
    Falls ein Spieler noch nicht existiert, wird ein neuer Eintrag angelegt.
    """
    global_data = load_global_data()
    player_stats = global_data.setdefault("player_stats", {})

    for mention in winner_mentions:
        match = re.search(r"\d+", mention)
        if not match:
            logger.warning(f"Ungültige Mention: {mention}")
            continue

        user_id = match.group(0)

        # Spieler existiert noch nicht ➔ anlegen
        stats = player_stats.get(user_id)
        if stats is None:
            stats = {
                "wins": 0,
                "participations": 0,
                "mention": f"<@{user_id}>",
                "display_name": f"User {user_id}",
                "game_stats": {}
            }

        # Statistiken aktualisieren
        stats["wins"] += 1
        stats["participations"] += 1

        player_stats[user_id] = stats

    global_data["player_stats"] = player_stats
    save_global_data(global_data)
    logger.info("Spielerstatistiken aktualisiert.")

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

def generate_team_name() -> str:
    """
    Erzeugt einen zufälligen Teamnamen aus einer Adjektiv- und einer Substantivliste.
    
    :return: Der generierte Teamname als String.
    """
    names = load_names()
    adjektiv = random.choice(names["adjektive"])
    substantiv = random.choice(names["substantive"])
    return f"{adjektiv} {substantiv}"

async def smart_send(interaction: Interaction, *, content: str = None, embed: Embed = None, ephemeral: bool = False):
    """
    Sendet eine Nachricht über interaction.response.send_message,
    oder über interaction.followup.send, falls bereits geantwortet wurde.
    """
    try:
        await interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)
    except discord.InteractionResponded:
        await interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)

    # Hilfsfunktion für zufällige Verfügbarkeiten

def parse_availability(avail_str: str) -> tuple[time, time]:
    """
    Wandelt einen String wie '12:00-18:00' in zwei datetime.time Objekte um.
    Überprüft, ob die Zeitspanne gültig ist (mindestens 1 Stunde Unterschied).
    """
    try:
        start_str, end_str = avail_str.split("-")
        start_time = datetime.strptime(start_str.strip(), "%H:%M").time()
        end_time = datetime.strptime(end_str.strip(), "%H:%M").time()

        # Zusätzliche Logik: Start muss vor Ende liegen
        start_dt = datetime.combine(datetime.today(), start_time)
        end_dt = datetime.combine(datetime.today(), end_time)

        if end_dt <= start_dt:
            raise ValueError(f"Endzeit muss nach Startzeit liegen: '{avail_str}'")

        # Mindestdauer: 1 Stunde
        if (end_dt - start_dt) < timedelta(hours=1):
            raise ValueError(f"Verfügbarkeit zu kurz: Mindestens 1 Stunde erforderlich – Eingabe: '{avail_str}'")

        return start_time, end_time

    except Exception as e:
        logger.warning(f"[AVAILABILITY] Fehler beim Parsen der Verfügbarkeit '{avail_str}': {e}")
        raise ValueError(f"Ungültiges Verfügbarkeitsformat: {avail_str}")

def intersect_availability(avail1: str, avail2: str) -> Optional[str]:
    """
    Berechnet die Schnittmenge von zwei Zeiträumen im Format 'HH:MM-HH:MM'.
    Gibt None zurück, wenn keine Überschneidung vorhanden ist.
    """
    try:
        start1_str, end1_str = avail1.split("-")
        start2_str, end2_str = avail2.split("-")

        start1 = datetime.strptime(start1_str, "%H:%M").time()
        end1 = datetime.strptime(end1_str, "%H:%M").time()
        start2 = datetime.strptime(start2_str, "%H:%M").time()
        end2 = datetime.strptime(end2_str, "%H:%M").time()

        latest_start = max(start1, start2)
        earliest_end = min(end1, end2)

        if latest_start >= earliest_end:
            return None  # Keine Überschneidung

        return f"{latest_start.strftime('%H:%M')}-{earliest_end.strftime('%H:%M')}"
    except Exception:
        return None

def get_player_team(user_mention_or_id: str) -> Optional[str]:
    """
    Findet das Team eines Spielers anhand seiner ID oder Mention.
    
    :param user_mention_or_id: String (Mention z.B. "<@123456789>" oder ID "123456789")
    :return: Teamname oder None
    """
    tournament = load_tournament_data()

    for team_name, team_data in tournament.get("teams", {}).items():
        for member in team_data.get("members", []):
            if user_mention_or_id in member:
                return team_name
    return None

def get_team_open_matches(team_name: str) -> list:
    """
    Gibt alle offenen Matches eines Teams zurück.
    
    :param team_name: Der Name des Teams
    :return: Liste von Match-Objekten
    """
    tournament = load_tournament_data()
    open_matches = []

    for match in tournament.get("matches", []):
        if match.get("status") != "erledigt" and (match.get("team1") == team_name or match.get("team2") == team_name):
            open_matches.append(match)

    return open_matches

async def autocomplete_players(interaction: Interaction, current: str):
    logger.info(f"[AUTOCOMPLETE] Aufgerufen – Eingabe: {current}")
    global_data = load_global_data()
    player_stats = global_data.get("player_stats", {})

    choices = []
    for user_id, stats in player_stats.items():
        member = interaction.guild.get_member(int(user_id))
        if member:
            display_name = member.display_name
        else:
            display_name = stats.get("display_name") or stats.get("name") or f"Unbekannt ({user_id})"
        
        if current.lower() in display_name.lower():
            choices.append(app_commands.Choice(name=display_name, value=user_id))

    return choices[:25]

async def autocomplete_teams(interaction: Interaction, current: str):
    logger.info(f"[AUTOCOMPLETE] Aufgerufen – Eingabe: {current}")

    tournament = load_tournament_data()
    if not tournament:
        logger.error("[AUTOCOMPLETE] Keine Turnierdaten geladen!")
        return []

    teams = tournament.get("teams", {})
    if not teams:
        logger.warning("[AUTOCOMPLETE] Keine Teams vorhanden im Turnier.")
        return []

    logger.info(f"[AUTOCOMPLETE] Gefundene Teams: {list(teams.keys())}")

    # Filtere die Teams, die zum aktuellen Eingabetext passen
    suggestions = [
        app_commands.Choice(name=team, value=team)
        for team in teams.keys()
        if current.lower() in team.lower()
    ][:25]

    logger.info(f"[AUTOCOMPLETE] {len(suggestions)} Vorschläge erstellt.")

    return suggestions

async def game_autocomplete(interaction: Interaction, current: str):
    games = load_games()

    return [
        app_commands.Choice(name=game, value=game)
        for game in games
        if current.lower() in game.lower()
    ][:25]  # Discord API erlaubt max 25 Ergebnisse

def all_matches_completed() -> bool:
    tournament = load_tournament_data()
    matches = tournament.get("matches", [])

    return all(match.get("status") == "completed" for match in matches)

def get_current_chosen_game() -> str:
    """
    Holt das aktuell gewählte Spiel aus der Tournament-Datei.
    """
    tournament = load_tournament_data()
    poll_results = tournament.get("poll_results") or {}

    chosen_game = poll_results.get("chosen_game", "Unbekannt")
    return chosen_game

async def update_all_participants():
    """
    Erhöht die Participation-Zahl für alle Teilnehmer eines Turniers.
    """
    global_data = load_global_data()
    player_stats = global_data.setdefault("player_stats", {})

    tournament = load_tournament_data()

    # Teams
    for team_entry in tournament.get("teams", {}).values():
        for member in team_entry.get("members", []):
            user_id = re.search(r"\d+", member).group(0)
            stats = player_stats.get(user_id)
            if stats is None:
                stats = {
                    "wins": 0,
                    "participations": 0,
                    "mention": f"<@{user_id}>",
                    "display_name": f"User {user_id}",
                    "game_stats": {}
                }
            stats["participations"] += 1
            player_stats[user_id] = stats

    # Solo-Spieler
    for solo_entry in tournament.get("solo", []):
        user_id = re.search(r"\d+", solo_entry.get("player")).group(0)
        stats = player_stats.get(user_id)
        if stats is None:
            stats = {
                "wins": 0,
                "participations": 0,
                "mention": f"<@{user_id}>",
                "display_name": f"User {user_id}",
                "game_stats": {}
            }
        stats["participations"] += 1
        player_stats[user_id] = stats

    global_data["player_stats"] = player_stats
    save_global_data(global_data)
    logger.info("[STATS] Participation-Zahlen für alle Teilnehmer aktualisiert.")

def cancel_all_tasks():
    for name, task in list(running_tasks.items()):
        if not task.done():
            task.cancel()
        running_tasks.pop(name, None)

def add_task(name, task):
    running_tasks[name] = task

# Hilfsfunktion für den dummy gen
def generate_random_availability() -> tuple[str, dict[str, str]]:
    """
    Generiert eine sinnvoll breite Verfügbarkeit für einen Dummy-Spieler:
    - Allgemein: 6–10 Stunden Zeitfenster
    - Samstag/Sonntag: extra spezielle Zeiten (optional)
    """
    start_hour = random.randint(8, 14)  # zwischen 08:00 und 14:00 starten
    duration = random.randint(6, 10)     # Verfügbarkeit 6 bis 10 Stunden
    end_hour = min(start_hour + duration, 23)

    allgemeine_verfugbarkeit = f"{start_hour:02d}:00-{end_hour:02d}:00"

    # Spezielle Verfügbarkeiten für Samstag und Sonntag (50% Chance)
    special = {}
    if random.random() < 0.5:
        start_samstag = random.randint(9, 14)
        end_samstag = min(start_samstag + random.randint(4, 8), 23)
        special["samstag"] = f"{start_samstag:02d}:00-{end_samstag:02d}:00"

    if random.random() < 0.5:
        start_sonntag = random.randint(9, 14)
        end_sonntag = min(start_sonntag + random.randint(4, 8), 23)
        special["sonntag"] = f"{start_sonntag:02d}:00-{end_sonntag:02d}:00"

    return allgemeine_verfugbarkeit, special


