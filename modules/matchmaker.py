# matchmaker.py
import logging
import random
from collections import defaultdict
from datetime import datetime, time, timedelta
from itertools import combinations
from math import ceil
from typing import Dict, List, Optional, Tuple
import os
import json

from discord import TextChannel

# Lokale Module
from modules.dataStorage import load_tournament_data, save_tournament_data
from modules.embeds import send_cleanup_summary
from modules.logger import logger
from modules.utils import generate_team_name

# Helper Variable
MATCH_DURATION = timedelta(minutes=90)
PAUSE_DURATION = timedelta(minutes=30)
MAX_TIME_BUDGET = timedelta(hours=2)

def auto_match_solo():
    """
    Paart Solo-Spieler in zufällige Teams und weist automatisch Teamnamen zu.
    """
    tournament = load_tournament_data()
    solo_players = tournament.get("solo", [])

    if len(solo_players) < 2:
        logger.info("[MATCHMAKER] Nicht genügend Solo-Spieler zum Paaren.")
        return  # Nicht genug Spieler zum Paaren

    random.shuffle(solo_players)  # Mischen für Zufälligkeit
    new_teams = {}

    while len(solo_players) >= 2:
        player1 = solo_players.pop()
        player2 = solo_players.pop()

        team_name = generate_team_name()

        # Stelle sicher, dass der Teamname noch nicht existiert
        existing_teams = tournament.get("teams", {}).keys()
        while team_name in existing_teams:
            team_name = generate_team_name()

        new_teams[team_name] = {
            "members": [player1["player"], player2["player"]],
            "verfügbarkeit": calculate_overlap(
                player1.get("verfügbarkeit", "00:00-23:59"),
                player2.get("verfügbarkeit", "00:00-23:59"),
            ),
        }

    # Update Turnierdaten
    tournament.setdefault("teams", {}).update(new_teams)
    tournament["solo"] = solo_players  # Restliche übriggebliebene Solospieler

    save_tournament_data(tournament)

    logger.info(f"[MATCHMAKER] {len(new_teams)} neue Teams aus Solo-Spielern erstellt: {', '.join(new_teams.keys())}")

    return new_teams


def create_round_robin_schedule():
    """
    Erstellt ein Round-Robin-Spielplan basierend auf den aktuellen Teams.
    """
    tournament = load_tournament_data()
    teams = list(tournament.get("teams", {}).keys())

    if len(teams) < 2:
        logger.warning("[MATCHMAKER] Nicht genügend Teams für einen Spielplan.")
        return []

    matches = []
    match_id = 1

    for team1, team2 in combinations(teams, 2):
        matches.append(
            {
                "match_id": match_id,
                "team1": team1,
                "team2": team2,
                "status": "offen",  # noch nicht gespielt
                "scheduled_time": None,
            }
        )
        match_id += 1

    tournament["matches"] = matches
    save_tournament_data(tournament)

    logger.info(f"[MATCHMAKER] {len(matches)} Matches für {len(teams)} Teams erstellt.")
    return matches


def calculate_overlap(zeitraum1: str, zeitraum2: str) -> str:
    """
    Berechnet die Überschneidung von zwei Zeiträumen im Format 'HH:MM-HH:MM'.

    :param zeitraum1: Erster Zeitraum als String.
    :param zeitraum2: Zweiter Zeitraum als String.
    :return: Der überlappende Zeitraum als String 'HH:MM-HH:MM', oder '00:00-00:00' wenn keine Überschneidung.
    """

    def parse_time_range(range_str):
        start_str, end_str = range_str.split("-")
        start = datetime.strptime(start_str, "%H:%M")
        end = datetime.strptime(end_str, "%H:%M")
        return start, end

    start1, end1 = parse_time_range(zeitraum1)
    start2, end2 = parse_time_range(zeitraum2)

    latest_start = max(start1, start2)
    earliest_end = min(end1, end2)

    if latest_start >= earliest_end:
        return "00:00-00:00"  # Keine Überschneidung

    return f"{latest_start.strftime('%H:%M')}-{earliest_end.strftime('%H:%M')}"


def generate_schedule_overview(matches: list) -> str:
    """
    Erzeugt einen schön gruppierten Spielplan aus der übergebenen Matchliste.
    Hebt Matches von HEUTE mit 🔥 hervor, erledigte Matches mit ✅.
    """
    if not matches:
        return "Keine Matches geplant."

    today = datetime.now().date()  # Heutiges Datum

    # Gruppiere nach Datum
    schedule_by_day = defaultdict(list)
    for match in matches:
        scheduled_time = match.get("scheduled_time")
        if scheduled_time:
            dt = datetime.fromisoformat(scheduled_time)
            day = dt.strftime("%d.%m.%Y %A")
            schedule_by_day[day].append((dt, match))  # Speichere datetime + Match

    description = ""
    for day, matches_list in sorted(
        schedule_by_day.items(),
        key=lambda x: datetime.strptime(x[0].split()[0], "%d.%m.%Y"),
    ):
        description += f"📅 {day}\n"

        # Sortiere die Matches an diesem Tag nach Uhrzeit
        matches_list.sort(key=lambda x: x[0])  # x[0] ist die datetime

        for dt, match in matches_list:
            team1 = match.get("team1", "Unbekannt")
            team2 = match.get("team2", "Unbekannt")
            match_status = match.get("status", "offen")

            # Emoji bestimmen
            if match_status == "erledigt":
                emoji = "✅"
            elif dt.date() == today:
                emoji = "🔥"
            else:
                emoji = "🕒"

            description += f"{emoji} {dt.strftime('%H:%M')} – **{team1}** vs **{team2}**\n"

        description += "\n"

    return description


async def cleanup_orphan_teams(channel: TextChannel):
    """
    Entfernt Teams mit nur 1 Spieler nach Anmeldeschluss
    und verschiebt sie in die Solo-Liste.
    """
    tournament = load_tournament_data()
    teams = tournament.get("teams", {})
    solo = tournament.get("solo", [])

    teams_deleted = 0
    players_rescued = 0

    for team_name, team_data in list(teams.items()):
        members = team_data.get("members", [])
        if len(members) == 1:
            # Nur 1 Spieler → auflösen
            player = members[0]
            solo.append(
                {
                    "player": player,
                    "verfügbarkeit": team_data.get("verfügbarkeit", "00:00-23:59"),
                    "samstag": team_data.get("samstag"),
                    "sonntag": team_data.get("sonntag"),
                }
            )
            del teams[team_name]
            teams_deleted += 1
            players_rescued += 1

    tournament["teams"] = teams
    tournament["solo"] = solo
    save_tournament_data(tournament)

    await send_cleanup_summary(channel, teams_deleted, players_rescued)

    logger.info(f"[CLEANUP] {teams_deleted} leere Teams gelöscht, {players_rescued} Spieler gerettet.")


def parse_start_hour(availability_str: str) -> int:
    """
    Extrahiert die Startstunde aus einem Zeitbereich (z.B. "12:00-20:00").
    """
    try:
        start_time = availability_str.split("-")[0]
        hour = int(start_time.split(":")[0])
        return hour
    except Exception:
        logger.warning(f"[SLOT-PLANUNG] Fehler beim Parsen der Verfügbarkeit: {availability_str}")
        return 10  # Falls etwas schiefgeht, Standardwert 10 Uhr


def team_available_on_slot(team_data, slot_datetime):
    """
    Prüft, ob das Team am Slot-Datum spielen darf (Blacklisted Dates).
    """
    unavailable = set(team_data.get("unavailable_dates", []))
    slot_date_str = slot_datetime.strftime("%Y-%m-%d")
    return slot_date_str not in unavailable


def get_team_time_budget(team_name: str, date: datetime.date, matches: list) -> timedelta:
    """
    Berechnet die gesamte Zeit, die ein Team an einem bestimmten Tag durch Matches + Pausen blockiert ist.
    """
    total_time = timedelta()

    for match in matches:
        scheduled = match.get("scheduled_time")
        if not scheduled:
            continue

        try:
            match_time = datetime.fromisoformat(scheduled)
        except ValueError:
            continue

        if match_time.date() != date:
            continue

        if team_name in (match.get("team1"), match.get("team2")):
            total_time += MATCH_DURATION + PAUSE_DURATION

    return total_time


def is_team_available_at_time(team_data: dict, slot_datetime: datetime) -> bool:
    """
    Prüft, ob ein Team zum gegebenen Zeitpunkt verfügbar ist.
    Beachtet samstags/sonntags explizite Zeitfenster im 'verfügbarkeit'-Dict.
    """
    weekday = slot_datetime.weekday()  # 5 = Samstag, 6 = Sonntag
    time_only = slot_datetime.time()

    day_key = "samstag" if weekday == 5 else "sonntag" if weekday == 6 else None
    if not day_key:
        return True  # Unter der Woche keine Einschränkung

    availability = team_data.get("verfügbarkeit", {})
    time_range = availability.get(day_key)

    if not time_range:
        return False  # Keine Zeit angegeben = nicht verfügbar

    try:
        start_str, end_str = time_range.split("-")
        start_time = datetime.strptime(start_str, "%H:%M").time()
        end_time = datetime.strptime(end_str, "%H:%M").time()
        return start_time <= time_only < end_time
    except Exception as e:
        logger.warning(f"[VERFÜGBARKEIT] Fehler beim Parsen der Zeit: {time_range} ({e})")
        return True  # Bei Fehlern lieber zulassen


def get_all_possible_slots(tournament: dict, slot_interval: int = 2) -> dict:
    """
    Berechnet pro Match alle potenziellen Slots auf Basis der Schnittmenge der Teamverfügbarkeiten.
    Gibt ein Dict zurück: {match_id: [datetime, ...]}
    """
    from_date = datetime.fromisoformat(tournament["registration_end"])
    to_date = datetime.fromisoformat(tournament["tournament_end"])
    matches = tournament.get("matches", [])
    teams = tournament.get("teams", {})

    all_slots = defaultdict(list)

    current = from_date
    while current <= to_date:
        if current.weekday() not in (5, 6):  # Nur Samstag und Sonntag
            current += timedelta(days=1)
            continue

        for hour in range(8, 22, slot_interval):
            slot = current.replace(hour=hour, minute=0, second=0, microsecond=0)

            for match in matches:
                team1 = teams.get(match["team1"])
                team2 = teams.get(match["team2"])
                if not team1 or not team2:
                    continue

                if (
                    team_available_on_slot(team1, slot)
                    and team_available_on_slot(team2, slot)
                    and is_team_available_at_time(team1, slot)
                    and is_team_available_at_time(team2, slot)
                ):
                    all_slots[match["match_id"]].append(slot)

        current += timedelta(days=1)

    # Optional: Debug-Log pro Match
    for match_id, slots in all_slots.items():
        logger.debug(f"[SLOT-GENERATOR] Match {match_id} hat {len(slots)} mögliche Slots.")

    # Optional: Slot-Matrix speichern, wenn DEBUG_MODE aktiv ist
    try:
        from modules.dataStorage import DEBUG_MODE  # falls nicht global importiert
        if DEBUG_MODE >= 1:
            debug_data = {
                match_id: [dt.strftime("%Y-%m-%d %H:%M") for dt in slot_list]
                for match_id, slot_list in all_slots.items()
            }
            with open("debug/slot_matrix_debug.json", "w", encoding="utf-8") as f:
                json.dump(debug_data, f, indent=2, ensure_ascii=False)
            logger.info("[SLOT-GENERATOR] Slot-Matrix als slot_matrix_debug.json gespeichert.")
    except Exception as e:
        logger.warning(f"[SLOT-GENERATOR] Fehler beim Speichern der Slot-Matrix: {e}")
    return dict(all_slots)

def is_minimum_pause_respected(last_slots: dict, team1: str, team2: str, new_slot: datetime, pause_minutes: int = 30) -> bool:
    """
    Prüft, ob beide Teams seit ihrem letzten Match mindestens X Minuten Pause hatten.
    """
    for team in (team1, team2):
        last = last_slots.get(team)
        if last:
            diff = (new_slot - last).total_seconds() / 60
            if diff < pause_minutes:
                logger.debug(f"[PAUSE] {team} hatte nur {diff:.0f} Min. Pause – benötigt: {pause_minutes} Min.")
                return False
    return True

def assign_best_slot_per_match(match_slots: dict, matches: list) -> list:
    """
    Versucht für jedes Match den besten Slot zu finden (erstmöglicher, nicht mehrfach genutzt),
    unter Berücksichtigung von Pausen und Tageszeit-Budget.
    """
    used_slots = set()
    assigned = 0
    last_slot_per_team = {}

    for match in matches:
        match_id = match["match_id"]
        possible_slots = match_slots.get(match_id, [])
        team1 = match["team1"]
        team2 = match["team2"]

        for slot in sorted(possible_slots):
            slot_str = slot.isoformat()
            slot_date = slot.date()

            # Prüfe Pausen zwischen Spielen
            if not is_minimum_pause_respected(last_slot_per_team, team1, team2, slot):
                logger.debug(f"[MATCHMAKER] Pausebedingung nicht erfüllt bei Match {match_id}.")
                continue

            # Slot schon belegt?
            if slot_str in used_slots:
                continue

            # Prüfe Teilnahme-Zeitbudget pro Tag
            team1_budget = get_team_time_budget(team1, slot_date, matches)
            team2_budget = get_team_time_budget(team2, slot_date, matches)

            if (
                team1_budget + MATCH_DURATION + PAUSE_DURATION > MAX_TIME_BUDGET
                or team2_budget + MATCH_DURATION + PAUSE_DURATION > MAX_TIME_BUDGET
            ):
                logger.debug(
                    f"[MATCHMAKER] Slot {slot_str} abgelehnt wegen Budget: "
                    f"{team1}={team1_budget}, {team2}={team2_budget}"
                )
                continue

            # Slot passt – Zuweisung
            match["scheduled_time"] = slot_str
            used_slots.add(slot_str)
            last_slot_per_team[team1] = slot
            last_slot_per_team[team2] = slot
            assigned += 1
            logger.info(f"[MATCHMAKER] Match {match_id} geplant auf {slot_str}.")
            break

        if not match.get("scheduled_time"):
            logger.warning(f"[MATCHMAKER] Kein Slot gefunden für Match {match_id}. Rescue wird benötigt.")

    logger.info(f"[MATCHMAKER] {assigned} Matches erfolgreich geplant.")
    return matches



async def generate_slots_from_team_availability():
    from modules.dataStorage import load_tournament_data, save_tournament_data

    tournament = load_tournament_data()
    matches = tournament.get("matches", [])

    if not matches:
        logger.warning("[MATCHMAKER] Keine Matches zum Planen vorhanden.")
        return

    slot_map = get_all_possible_slots(tournament)
    updated_matches = assign_best_slot_per_match(slot_map, matches)
    tournament["matches"] = updated_matches
    save_tournament_data(tournament)

    logger.info("[MATCHMAKER] Dynamische Slot-Zuweisung abgeschlossen.")


# ------------------
# Alles zusammenbauen
# ------------------
async def generate_and_assign_slots():
    """
    Hauptfunktion zur Slot-Erzeugung und Zuweisung der Matches.
    """
    tournament = load_tournament_data()
    matches = tournament.get("matches", [])

    if not matches:
        logger.warning(
            "[CLOSE REGISTRATION] Keine Matches im Turnier gefunden. Registrierung beendet, aber es gibt nichts zu planen."
        )
        return  # Crash handler

    await generate_slots_from_team_availability()
    return
    tournament["matches"] = matches

    save_tournament_data(tournament)
    logger.info("[MATCHMAKER] Matches erfolgreich auf Slots verteilt.")
