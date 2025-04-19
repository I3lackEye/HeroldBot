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
from .dataStorage import load_tournament_data, save_tournament_data
from .logger import setup_logger
from .utils import generate_team_name, generate_weekend_slots
from .embeds import send_cleanup_summary

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
            "scheduled_time": None 
        })
        match_id += 1

    tournament["matches"] = matches
    save_tournament_data(tournament)

    logger.info(f"[MATCHMAKER] {len(matches)} Matches für {len(teams)} Teams erstellt.")
    return matches

async def assign_matches_to_slots():
    """
    Ordnet Matches passenden Slots zu mit "Soft-Cooldown" zwischen Matches.
    (Vermeidet direktes Hintereinander-Spielen wenn möglich.)
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

    # Vorbereiten
    scheduled_matches = {}
    for match in matches:
        match["scheduled_time"] = None

    team_slots = {team_name: calculate_team_slots(team_entry, available_slots) for team_name, team_entry in teams.items()}

    def has_recent_match(team_name, slot_time):
        """Prüfe, ob Team kurz vor oder nach dem Slot spielt."""
        for scheduled_time, teams_in_match in scheduled_matches.items():
            if team_name in teams_in_match:
                diff = abs((slot_time - scheduled_time).total_seconds()) / 60  # Minuten
                if diff <= 30:  # innerhalb einer halben Stunde
                    return True
        return False

    # Matches verteilen
    for match in matches:
        team1 = match["team1"]
        team2 = match["team2"]

        slots_team1 = set(team_slots.get(team1, []))
        slots_team2 = set(team_slots.get(team2, []))

        common_slots = sorted(slots_team1 & slots_team2)

        if not common_slots:
            logger.warning(f"[MATCHMAKER] Kein gemeinsamer Slot für {team1} vs {team2} gefunden!")
            continue

        best_slot = None

        for slot in common_slots:
            slot_time = datetime.strptime(slot, "%Y-%m-%dT%H:%M:%S")
            if not (has_recent_match(team1, slot_time) or has_recent_match(team2, slot_time)):
                best_slot = slot
                break

        # Wenn kein "perfekter" Slot, dann einfach den ersten nehmen
        if not best_slot:
            best_slot = common_slots[0]

        # Slot zuweisen
        match["scheduled_time"] = best_slot
        scheduled_matches[datetime.strptime(best_slot, "%Y-%m-%dT%H:%M:%S")] = {team1, team2}

        # Slot für beide Teams blockieren
        team_slots[team1].remove(best_slot)
        team_slots[team2].remove(best_slot)

    save_tournament_data(tournament)
    logger.info("[MATCHMAKER] Alle Matches verteilt unter Berücksichtigung von Pausen.")

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
    Ermittelt verfügbare Slots für ein Team auf Basis von special_availability oder allgemeiner Verfügbarkeit.
    """
    from .utils import parse_availability

    team_slots = set()
    special = team_entry.get("special_availability", {})

    for slot in available_slots:
        dt = datetime.strptime(slot, "%Y-%m-%dT%H:%M:%S")
        weekday = dt.strftime("%A").lower()  # z.B. "saturday" oder "sunday"

        # Falls spezielle Verfügbarkeit für diesen Tag existiert
        if weekday in special:
            start_time, end_time = parse_availability(special[weekday])
        else:
            # Normale Verfügbarkeit
            start_time, end_time = parse_availability(team_entry.get("verfügbarkeit", "00:00-23:59"))

        # Check, ob Slot innerhalb der Zeiten liegt
        if start_time <= dt.time() <= end_time:
            team_slots.add(slot)

    return list(sorted(team_slots))

def generate_schedule_overview():
    tournament = load_tournament_data()
    matches = tournament.get("matches", [])
    
    if not matches:
        return "Keine Matches geplant."

    # Gruppiere nach Datum
    schedule_by_day = defaultdict(list)
    for match in matches:
        scheduled_time = match.get("scheduled_time")
        if scheduled_time:
            dt = datetime.strptime(scheduled_time, "%Y-%m-%dT%H:%M:%S")
            day = dt.strftime("%d.%m.%Y %A")
            schedule_by_day[day].append((dt, match))  # Speichere datetime + Match

    description = ""
    for day, matches_list in sorted(schedule_by_day.items()):
        description += f"📅 {day}\n"

        # Sortiere die Matches an diesem Tag nach Uhrzeit
        matches_list.sort(key=lambda x: x[0])

        for dt, match in matches_list:
            team1 = match.get("team1", "Unbekannt")
            team2 = match.get("team2", "Unbekannt")
            description += f"🕒 {dt.strftime('%H:%M')} – **{team1}** vs **{team2}**\n"

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
            solo.append({
                "player": player,
                "verfügbarkeit": team_data.get("verfügbarkeit", "00:00-23:59"),
                "samstag": team_data.get("samstag"),
                "sonntag": team_data.get("sonntag")
            })
            del teams[team_name]
            teams_deleted += 1
            players_rescued += 1

    tournament["teams"] = teams
    tournament["solo"] = solo
    save_tournament_data(tournament)

    await send_cleanup_summary(channel, teams_deleted, players_rescued)

    logger.info(f"[CLEANUP] {teams_deleted} leere Teams gelöscht, {players_rescued} Spieler gerettet.")


