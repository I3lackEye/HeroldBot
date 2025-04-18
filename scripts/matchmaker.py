# matchmaker.py
import random
import logging
from itertools import combinations
from collections import defaultdict
from datetime import datetime, timedelta, time
from typing import Optional, List, Tuple, Dict

# Lokale Module
from .dataStorage import load_tournament_data, save_tournament_data
from .logger import setup_logger
from .utils import generate_team_name, generate_weekend_slots

# Setup logger
logger = setup_logger("logs", level=logging.INFO)

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
                player2.get("verfügbarkeit", "00:00-23:59")
            )
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
        matches.append({
            "match_id": match_id,
            "team1": team1,
            "team2": team2,
            "status": "offen",  # noch nicht gespielt
            "scheduled_time": None  # später
        })
        match_id += 1

    tournament["matches"] = matches
    save_tournament_data(tournament)

    logger.info(f"[MATCHMAKER] {len(matches)} Matches für {len(teams)} Teams erstellt.")
    return matches

def assign_matches_to_slots():
    """
    Ordnet Matches passenden Slots zu – nur an Samstagen/Sonntagen.
    """
    tournament = load_tournament_data()
    matches = tournament.get("matches", [])
    teams = tournament.get("teams", {})

    if not matches or not teams:
        logger.warning("[MATCHMAKER] Keine Matches oder Teams zum Planen gefunden.")
        return

    registration_end = datetime.fromisoformat(tournament.get("registration_end"))
    tournament_end = datetime.fromisoformat(tournament.get("tournament_end"))
    available_slots = generate_weekend_slots(registration_end, tournament_end)

    if not available_slots:
        logger.warning("[MATCHMAKER] Keine verfügbaren Wochenendslots gefunden.")
        return

    team_slots = {team_name: calculate_team_slots(team_entry, available_slots) for team_name, team_entry in teams.items()}

    for match in matches:
        team1 = match["team1"]
        team2 = match["team2"]

        slots_team1 = set(team_slots.get(team1, []))
        slots_team2 = set(team_slots.get(team2, []))

        common_slots = sorted(slots_team1 & slots_team2)

        if not common_slots:
            logger.warning(f"[MATCHMAKER] Kein gemeinsamer Slot für {team1} vs {team2} gefunden!")
            continue

        chosen_slot = common_slots[0]
        match["scheduled_time"] = chosen_slot

        team_slots[team1].remove(chosen_slot)
        team_slots[team2].remove(chosen_slot)

    save_tournament_data(tournament)
    logger.info("[MATCHMAKER] Alle Matches für Wochenenden zeitlich eingeplant.")

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

def calculate_team_slots(team_entry: dict, available_slots: list[str]) -> list[str]:
    """
    Ermittelt die verfügbaren Slots eines Teams basierend auf dem Wochenend-Zeitplan.
    """
    team_availability = team_entry.get("verfügbarkeit", "00:00-23:59")
    start_time, end_time = team_availability.split("-")

    available_for_team = []

    for slot in available_slots:
        slot_dt = datetime.fromisoformat(slot)
        slot_time_str = slot_dt.strftime("%H:%M")
        if start_time <= slot_time_str <= end_time:
            available_for_team.append(slot)

    return available_for_team

def generate_schedule_overview() -> str:
    """
    Erstellt eine schöne Übersicht des aktuellen Spielplans.
    """
    tournament = load_tournament_data()
    matches = tournament.get("matches", [])

    if not matches:
        return "⚠️ Keine Matches vorhanden."

    schedule_by_day = defaultdict(list)
    unscheduled_matches = []

    for match in matches:
        scheduled_time = match.get("scheduled_time")

        if scheduled_time:
            dt = datetime.strptime(scheduled_time, "%Y-%m-%dT%H:%M:%S")
            day_key = dt.strftime("%d.%m.%Y %A")  # z.B. 26.04.2025 Samstag
            time_str = dt.strftime("%H:%M")

            schedule_by_day[day_key].append(f"🕒 {time_str} - **{match['team1']}** vs **{match['team2']}**")
        else:
            unscheduled_matches.append(f"- **{match['team1']}** vs **{match['team2']}**")

    # Aufbau der Ausgabe
    parts = []

    for day, matches_list in sorted(schedule_by_day.items()):
        parts.append(f"📅 {day}")
        parts.extend(matches_list)
        parts.append("")  # Leere Zeile als Trenner

    if unscheduled_matches:
        parts.append("⚠️ **Keine Terminüberschneidung:**")
        parts.extend(unscheduled_matches)

    return "\n".join(parts)