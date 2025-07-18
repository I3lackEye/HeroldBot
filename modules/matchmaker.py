# matchmaker.py
import json
import logging
import os
import random
from collections import defaultdict
from datetime import datetime, time, timedelta
from itertools import combinations
from zoneinfo import ZoneInfo
from math import ceil
from typing import Dict, List, Optional, Tuple

from discord import TextChannel

# Lokale Module
from modules.dataStorage import DEBUG_MODE, load_tournament_data, save_tournament_data
from modules.embeds import send_cleanup_summary
from modules.logger import logger
from modules.utils import generate_team_name, get_active_days_config

# Helper Variable
MATCH_DURATION = timedelta(minutes=90)
PAUSE_DURATION = timedelta(minutes=30)
MAX_TIME_BUDGET = timedelta(hours=2)


# ---------------------------------------
# Hilfsfunktion
# ---------------------------------------
def merge_weekend_availability(avail1: dict, avail2: dict) -> dict:
    result = {}
    for day in ["samstag", "sonntag"]:
        slot1 = avail1.get(day, "00:00-00:00")
        slot2 = avail2.get(day, "00:00-00:00")
        overlap = calculate_overlap(slot1, slot2)
        result[day] = overlap
    return result


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


def auto_match_solo():
    """
    Paart Solo-Spieler basierend auf gemeinsamer Verfügbarkeit für Samstag/Sonntag.
    Speichert nur funktionierende Teams.
    """
    tournament = load_tournament_data()
    solo_players = tournament.get("solo", [])

    if len(solo_players) < 2:
        logger.info("[MATCHMAKER] Nicht genügend Solo-Spieler zum Paaren.")
        return []

    logger.debug(f"[MATCHMAKER] Solo-Spieler (Rohdaten): {solo_players}")

    random.shuffle(solo_players)
    new_teams = {}
    used_names = set(tournament.get("teams", {}).keys())

    while len(solo_players) >= 2:
        p1 = solo_players.pop()
        p2 = solo_players.pop()
        name1 = p1.get("player", "???")
        name2 = p2.get("player", "???")

        logger.debug(f"[MATCHMAKER] Paarung: {name1} + {name2}")

        avail1 = p1.get("verfügbarkeit", {})
        avail2 = p2.get("verfügbarkeit", {})

        overlap = merge_weekend_availability(avail1, avail2)

        if all(val == "00:00-00:00" for val in overlap.values()):
            logger.warning(f"[MATCHMAKER] ❌ Keine gemeinsame Verfügbarkeit für {name1} und {name2} – Team wird nicht erstellt.")
            continue

        team_name = generate_team_name()
        attempts = 0
        while team_name in used_names or team_name in new_teams:
            team_name = generate_team_name()
            attempts += 1
            if attempts > 10:
                logger.error("[MATCHMAKER] ❌ Kein eindeutiger Teamname gefunden – Abbruch.")
                break
        used_names.add(team_name)

        new_teams[team_name] = {
            "members": [name1, name2],
            "verfügbarkeit": overlap,
        }

    if new_teams:
        tournament.setdefault("teams", {}).update(new_teams)
        tournament["solo"] = solo_players
        save_tournament_data(tournament)
        logger.info(f"[MATCHMAKER] ✅ {len(new_teams)} Teams erstellt: {', '.join(new_teams.keys())}")
    else:
        logger.warning("[MATCHMAKER] ❌ Keine Teams erstellt – nichts gespeichert.")

    return list(new_teams.keys())


def create_round_robin_schedule(tournament: dict):
    """
    Erstellt ein Round-Robin-Spielplan basierend auf den aktuellen Teams.
    """
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


def generate_schedule_overview(matches: list) -> str:
    """
    Erzeugt einen schön gruppierten Spielplan aus der übergebenen Matchliste.
    Hebt Matches von HEUTE mit 🔥 hervor, erledigte Matches mit ✅.
    """
    logger.debug(f"[DEBUG] {len(matches)} Matches erhalten.")
    scheduled_count = sum(1 for m in matches if m.get("scheduled_time"))
    logger.debug(f"[DEBUG] Davon mit scheduled_time: {scheduled_count}")

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
            if match.get("rescue_assigned"):
                emoji = "❗"
            elif match_status == "erledigt":
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


def get_compatible_slots(team1: dict, team2: dict, global_slots: list) -> list:
    """
    Gibt eine Liste von Slots zurück, die innerhalb der gemeinsamen Verfügbarkeit beider Teams liegen.
    Erwartet Slot-Times als UTC (ISO), Team-Verfügbarkeit als { "samstag": "HH:MM-HH:MM", ... }
    """
    compatible = []

    # hole die Teamverfügbarkeit
    avail1 = team1.get("verfügbarkeit", {})
    avail2 = team2.get("verfügbarkeit", {})

    for slot_str in global_slots:
        try:
            slot_dt = datetime.fromisoformat(slot_str).astimezone(ZoneInfo("Europe/Berlin"))
            tag = slot_dt.strftime("%A").lower()  # z. B. "samstag"
            uhrzeit = slot_dt.strftime("%H:%M")

            # nur wenn Tag in beiden vorhanden
            if tag not in avail1 or tag not in avail2:
                continue

            start1, end1 = avail1[tag].split("-")
            start2, end2 = avail2[tag].split("-")

            # Slot muss in beiden Zeiträumen liegen
            if start1 <= uhrzeit <= end1 and start2 <= uhrzeit <= end2:
                compatible.append(slot_str)
        except Exception as e:
            logger.warning(f"[SLOTS] Fehler beim Verarbeiten von Slot {slot_str}: {e}")

    return compatible


# ---------------------------------------
# Main Matchmaker
# ---------------------------------------
def generate_slot_matrix(tournament: dict, slot_interval: int = 2) -> dict:
    """
    Erstellt eine globale Slot-Matrix, die angibt, welche Teams an welchen Slots verfügbar sind.
    Gibt zurück: Dict[datetime, Set[team_name]]
    """
    from datetime import datetime, timedelta
    from collections import defaultdict

    from_date = datetime.fromisoformat(tournament["registration_end"])
    to_date = datetime.fromisoformat(tournament["tournament_end"])
    teams = tournament.get("teams", {})

    slot_matrix = defaultdict(set)

    current = from_date
    while current <= to_date:
        active_days = get_active_days_config()
        weekday = current.weekday()
        if str(weekday) not in active_days:
            current += timedelta(days=1)
            continue

        start_str = active_days[str(weekday)]["start"]
        end_str = active_days[str(weekday)]["end"]
        start_hour = int(start_str.split(":")[0])
        end_hour = int(end_str.split(":")[0])

        for hour in range(start_hour, end_hour, slot_interval):
            slot = current.replace(hour=hour, minute=0, second=0, microsecond=0)

            for team_name, team_data in teams.items():
                if (
                    team_available_on_slot(team_data, slot)
                    and is_team_available_at_time(team_data, slot)
                ):
                    slot_matrix[slot].add(team_name)

        current += timedelta(days=1)

    # Optional: JSON-Debug speichern
    if DEBUG_MODE:
        try:
            os.makedirs("debug", exist_ok=True)

            debug_data = []
            for dt, teamset in sorted(slot_matrix.items()):
                debug_data.append({
                    "slot": dt.strftime("%Y-%m-%d %H:%M"),
                    "weekday": dt.strftime("%A"),
                    "team_count": len(teamset),
                    "teams": sorted(teamset),
                })

            with open("debug/slot_matrix_debug.json", "w", encoding="utf-8") as f:
                json.dump(debug_data, f, indent=2, ensure_ascii=False)

            logger.info("[SLOT-MATRIX] slot_matrix_debug.json gespeichert.")
        except Exception as e:
            logger.warning(f"[SLOT-MATRIX] Fehler beim Speichern: {e}")

    return dict(slot_matrix)


def get_valid_slots_for_match(team1: str, team2: str, slot_matrix: dict[datetime, set[str]]) -> list[datetime]:
    """
    Gibt alle Slots zurück, an denen sowohl team1 als auch team2 verfügbar sind.
    """
    valid_slots = []
    for slot_time, team_set in slot_matrix.items():
        if team1 in team_set and team2 in team_set:
            valid_slots.append(slot_time)

    return sorted(valid_slots)


def assign_slots_with_matrix(matches: list, slot_matrix: dict[datetime, set[str]]) -> tuple[list, list]:
    """
    Weist Matches anhand der globalen Slot-Matrix Slots zu.
    Berücksichtigt Pause + Zeitbudget + Dopplungen.
    Gibt (updated_matches, unassigned_matches) zurück.
    """
    used_slots = set()
    last_slot_per_team = {}
    unassigned_matches = []

    matches_with_options = []

    for match in matches:
        team1 = match["team1"]
        team2 = match["team2"]
        match_id = match["match_id"]

        valid_slots = get_valid_slots_for_match(team1, team2, slot_matrix)

        matches_with_options.append((match, valid_slots))

    # Matches mit wenigsten Optionen zuerst
    matches_with_options.sort(key=lambda x: len(x[1]))

    for match, valid_slots in matches_with_options:
        team1 = match["team1"]
        team2 = match["team2"]
        match_id = match["match_id"]

        for slot in valid_slots:
            slot_str = slot.isoformat()
            slot_date = slot.date()

            # Slot bereits belegt?
            if slot_str in used_slots:
                continue

            # Pausenregel beachten
            if not is_minimum_pause_respected(last_slot_per_team, team1, team2, slot):
                continue

            # Tageszeitbudget prüfen
            team1_budget = get_team_time_budget(team1, slot_date, matches)
            team2_budget = get_team_time_budget(team2, slot_date, matches)

            if (
                team1_budget + MATCH_DURATION + PAUSE_DURATION > MAX_TIME_BUDGET
                or team2_budget + MATCH_DURATION + PAUSE_DURATION > MAX_TIME_BUDGET
            ):
                continue

            # Slot passt – zuweisen
            match["scheduled_time"] = slot_str
            used_slots.add(slot_str)
            last_slot_per_team[team1] = slot
            last_slot_per_team[team2] = slot
            logger.info(f"[SLOT-MATRIX] Match {match_id} geplant auf {slot_str}.")
            break

        if not match.get("scheduled_time"):
            unassigned_matches.append(match)
            logger.warning(f"[SLOT-MATRIX] Kein Slot gefunden für Match {match_id} ({team1} vs {team2})")

    return matches, unassigned_matches


def is_minimum_pause_respected(
    last_slots: dict, team1: str, team2: str, new_slot: datetime, pause_minutes: int = 30
 ) -> bool:
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


def assign_rescue_slots(unassigned_matches, matches, slot_matrix, teams):
    """
    Versucht Matches aus der unassigned_matches-Liste trotzdem zu planen,
    indem Pausen und Zeitbudget ignoriert werden.
    Markiert diese mit 'rescue_assigned': True.
    """
    rescue_assigned = 0
    used_slots = set(m.get("scheduled_time") for m in matches if m.get("scheduled_time"))

    logger.info(f"[RESCUE] Starte Rescue-Modus für {len(unassigned_matches)} Matches.")

    for problem in unassigned_matches:
        match_id = problem["match_id"]
        team1 = problem["team1"]
        team2 = problem["team2"]

        match = next((m for m in matches if m["match_id"] == match_id), None)
        if not match:
            continue

        possible_slots = get_valid_slots_for_match(team1, team2, slot_matrix)
        if not possible_slots:
            logger.warning(f"[RESCUE] Keine gemeinsamen Slots für Match {match_id}.")
            continue

        for slot in possible_slots:
            slot_str = slot.isoformat()
            if slot_str in used_slots:
                continue  # Slot schon vergeben

            # Slot zuweisen – ohne Rücksicht auf Pausen/Budget
            match["scheduled_time"] = slot_str
            match["rescue_assigned"] = True
            used_slots.add(slot_str)
            rescue_assigned += 1

            logger.info(
                f"[RESCUE] Match {match_id} ({team1} vs {team2}) geplant auf {slot_str} "
                f"(Regeln gelockert – Rescue-Modus)"
            )
            break

        if not match.get("scheduled_time"):
            logger.warning(
                f"[RESCUE] Selbst im Rescue-Modus kein Slot für Match {match_id} ({team1} vs {team2}) gefunden."
            )

    logger.info(f"[RESCUE] Insgesamt {rescue_assigned} Matches im Rescue-Modus zugewiesen.")
    return matches

d
# ------------------
# Alles zusammenbauen
# ------------------
async def generate_and_assign_slots():
    """
    Hauptfunktion zur Slot-Erzeugung und Zuweisung der Matches.
    Nutzt globale Slot-Matrix und neue Zuweisungslogik.
    """
    tournament = load_tournament_data()
    matches = tournament.get("matches", [])
    teams = tournament.get("teams", {})

    if not matches:
        logger.warning(
            "[SLOT-PLANUNG] Keine Matches im Turnier gefunden. Registrierung beendet, aber es gibt nichts zu planen."
        )
        return

    # Schritt 1: Slot-Matrix erzeugen
    slot_matrix = generate_slot_matrix(tournament)

    # Schritt 2: Slots pro Match zuweisen
    updated_matches, unassigned_matches = assign_slots_with_matrix(matches, slot_matrix)

    # Schritt 3: Rescue-Modus für ungeplante Matches
    updated_matches = assign_rescue_slots(unassigned_matches, updated_matches, slot_matrix, teams)

    # Speichern
    tournament["matches"] = updated_matches
    save_tournament_data(tournament)

    logger.info("[MATCHMAKER] Matches erfolgreich über globale Slot-Matrix geplant.")

