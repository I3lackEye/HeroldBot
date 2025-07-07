# matchmaker.py
import random
import logging

from math import ceil
from itertools import combinations
from collections import defaultdict
from datetime import datetime, timedelta, time
from typing import Optional, List, Tuple, Dict
from discord import TextChannel


# Lokale Module
from modules.dataStorage import load_tournament_data, save_tournament_data
from modules.logger import logger
from modules.utils import generate_team_name
from modules.embeds import send_cleanup_summary


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

    logger.info(
        f"[MATCHMAKER] {len(new_teams)} neue Teams aus Solo-Spielern erstellt: {', '.join(new_teams.keys())}"
    )

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
            dt = datetime.strptime(scheduled_time, "%Y-%m-%dT%H:%M:%S")
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

            description += (
                f"{emoji} {dt.strftime('%H:%M')} – **{team1}** vs **{team2}**\n"
            )

        description += "\n"

    description += "*Spielplan wird automatisch aktualisiert.*"
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

    logger.info(
        f"[CLEANUP] {teams_deleted} leere Teams gelöscht, {players_rescued} Spieler gerettet."
    )


def parse_start_hour(availability_str: str) -> int:
    """
    Extrahiert die Startstunde aus einem Zeitbereich (z.B. "12:00-20:00").
    """
    try:
        start_time = availability_str.split("-")[0]
        hour = int(start_time.split(":")[0])
        return hour
    except Exception:
        logger.warning(
            f"[SLOT-PLANUNG] Fehler beim Parsen der Verfügbarkeit: {availability_str}"
        )
        return 10  # Falls etwas schiefgeht, Standardwert 10 Uhr


def team_available_on_slot(team_data, slot_datetime):
    """
    Prüft, ob das Team am Slot-Datum spielen darf (Blacklisted Dates).
    """
    unavailable = set(team_data.get("unavailable_dates", []))
    slot_date_str = slot_datetime.strftime("%Y-%m-%d")
    return slot_date_str not in unavailable


# ------------------
# Dynamische Slot-Generierung
# ------------------
def calculate_dynamic_first_hour(tournament: dict) -> int:
    """
    Bestimmt die früheste verfügbare Startstunde aller Teams.
    Fällt zurück auf 10 Uhr, falls keine Verfügbarkeiten gefunden werden können.
    """
    solo_players = tournament.get("solo", [])
    teams = tournament.get("teams", {})

    earliest_hours = []

    # Solo-Spieler durchgehen
    for player in solo_players:
        availability = player.get("verfügbarkeit")
        if availability:
            start_hour = parse_start_hour(availability)
            earliest_hours.append(start_hour)

    # Teams durchgehen
    for team_data in teams.values():
        availability = team_data.get("verfügbarkeit")
        if availability:
            start_hour = parse_start_hour(availability)
            earliest_hours.append(start_hour)

    if earliest_hours:
        return min(earliest_hours)

    # Fallback auf 10 Uhr
    return 10


def generate_weekend_slots(tournament: dict) -> list:
    """
    Generiert verfügbare Zeitslots für Matches.
    """
    slots = []
    matches = tournament.get("matches", [])
    if not matches:
        raise ValueError("Keine Matches im Turnier gefunden!")

    registration_end = datetime.fromisoformat(tournament.get("registration_end"))
    tournament_end = datetime.fromisoformat(tournament.get("tournament_end"))

    current_date = registration_end
    weekend_days = []

    while current_date <= tournament_end:
        if current_date.weekday() in (5, 6):
            weekend_days.append(current_date)
        current_date += timedelta(days=1)

    total_days = len(weekend_days)
    total_matches = len(matches)

    if total_days == 0:
        raise ValueError("Keine Wochenendtage im angegebenen Zeitraum gefunden!")

    first_hour = calculate_dynamic_first_hour(tournament)
    slot_interval = 2

    required_slots_per_day = ceil(total_matches / total_days)
    max_slots_per_day = 3  # How many matches per day!
    slots_per_day = min(required_slots_per_day, max_slots_per_day)

    for day in weekend_days:
        for i in range(slots_per_day):
            hour = first_hour + (i * slot_interval)
            if hour >= 24:
                break
            slot_time = day.replace(hour=hour, minute=0, second=0, microsecond=0)
            slots.append(slot_time.strftime("%Y-%m-%dT%H:%M:%S"))

    logger.info(f"[SLOT-PLANUNG] Gesamtmatches: {total_matches}")
    logger.info(f"[SLOT-PLANUNG] Wochenendtage gefunden: {total_days}")
    logger.info(
        f"[SLOT-PLANUNG] Erforderliche Slots pro Tag: {required_slots_per_day} (begrenzt auf {slots_per_day})"
    )
    logger.info(f"[SLOT-PLANUNG] Insgesamt {len(slots)} Slots generiert.")

    return slots


# ------------------
# Matches zu Slots zuweisen
# ------------------
def assign_matches_to_slots(matches: list, slots: list, tournament: dict):
    logger.info(
        f"[MATCHMAKER] Starte Slot-Zuweisung für {len(matches)} Matches auf {len(slots)} Slots."
    )
    scheduled_slots = set()
    team_last_slot = {}
    team_matches_per_day = {}

    teams = tournament.get("teams", {})

    for match in matches:
        team1 = match["team1"]
        team2 = match["team2"]
        assigned = False

        for slot in slots:
            slot_datetime = datetime.fromisoformat(slot)
            slot_date = slot_datetime.strftime("%Y-%m-%d")

            # Blacklist: Dürfen beide Teams?
            if not team_available_on_slot(teams[team1], slot_datetime):
                continue
            if not team_available_on_slot(teams[team2], slot_datetime):
                continue

            # Team darf nicht zweimal hintereinander (vergleiche letzten Slot)
            if team_last_slot.get(team1) == slot or team_last_slot.get(team2) == slot:
                continue

            # Optional: Max. 1 Match pro Tag für ein Team
            if team_matches_per_day.get((team1, slot_date)) or team_matches_per_day.get(
                (team2, slot_date)
            ):
                continue

            # Optional: Pause zwischen Spielen
            if (
                team_last_slot.get(team1)
                and (
                    slot_datetime - datetime.fromisoformat(team_last_slot[team1])
                ).total_seconds()
                < 30 * 60
            ):
                continue
            if (
                team_last_slot.get(team2)
                and (
                    slot_datetime - datetime.fromisoformat(team_last_slot[team2])
                ).total_seconds()
                < 30 * 60
            ):
                continue

            match["scheduled_time"] = slot
            scheduled_slots.add(slot)
            team_last_slot[team1] = slot
            team_last_slot[team2] = slot
            team_matches_per_day[(team1, slot_date)] = True
            team_matches_per_day[(team2, slot_date)] = True
            assigned = True

            logger.info(f"[MATCHMAKER] {team1} vs {team2} eingeplant am {slot}.")
            break

        if not assigned:
            logger.warning(
                f"[MATCHMAKER] Rescue-Modus: Kein freier Slot für {team1} vs {team2} ohne Konflikte. Erzwinge Zuweisung."
            )
            for slot in slots:
                if slot not in scheduled_slots:
                    match["scheduled_time"] = slot
                    scheduled_slots.add(slot)
                    logger.warning(
                        f"[MATCHMAKER] [RESCUE] {team1} vs {team2} auf {slot} zwangsweise gelegt."
                    )
                    break

    logger.info(
        f"[MATCHMAKER] Slot-Zuweisung abgeschlossen. {len(scheduled_slots)} Slots wurden belegt."
    )


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

    slots = generate_weekend_slots(tournament)

    assign_matches_to_slots(matches, slots)
    tournament["matches"] = matches

    save_tournament_data(tournament)
    logger.info("[MATCHMAKER] Matches erfolgreich auf Slots verteilt.")
