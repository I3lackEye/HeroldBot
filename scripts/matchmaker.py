# matchmaker.py
import random
import logging
from datetime import datetime, timedelta, time
from typing import Optional, List, Tuple, Dict
from .dataStorage import load_tournament_data, save_tournament_data
from .logger import setup_logger

# Setup logger
logger = setup_logger("logs", level=logging.INFO)

def auto_match_solo():
    """
    Gruppiert Spieler aus der Solo-Liste paarweise zu Teams und speichert sie in tournament["teams"].
    
    Falls eine ungerade Anzahl vorhanden ist, bleibt der letzte Spieler in der Solo-Liste.
    Es werden neue Teamnamen generiert, z.B. "Team 1", "Team 2", etc.
    
    :return: Ein Dictionary mit den neuen Teams und deren Mitglieder.
    """
    tournament = load_tournament_data()
    solo_list = tournament.get("solo", [])
    
    # Kopie der Solo-Liste, damit das Original nicht direkt verändert wird (optional)
    players = solo_list.copy()
    
    # Optional: Mische die Liste, um zufällige Teams zu generieren
    random.shuffle(players)
    
    new_teams = {}
    team_counter = 1
    
    # Paare bilden solange mindestens 2 Spieler vorhanden sind
    while len(players) >= 2:
        # Entnimm die ersten zwei Spieler
        player1 = players.pop(0)
        player2 = players.pop(0)
        team_name = f"Team {team_counter}"
        new_teams[team_name] = [player1, player2]
        team_counter += 1

    # Aktualisiere den Turnier-Datensatz:
    # Füge die neuen Teams zu den bereits angemeldeten Teams hinzu.
    # (Alternativ können die Teams auch komplett ersetzen werden)
    tournament["teams"].update(new_teams)
    # Aktualisiere die Solo-Liste. Falls ein Spieler übrig blieb, wird er beibehalten.
    tournament["solo"] = players
    save_tournament_data(tournament)
    return new_teams

def parse_time_range(time_range: str) -> Optional[Tuple[time, time]]:
    """
    Nimmt einen Zeitbereich im Format "HH:MM-HH:MM" und gibt ein Tuple (start, end) als datetime.time-Objekte zurück.
    Falls das Format nicht stimmt, wird None zurückgegeben.
    """
    try:
        parts = time_range.split("-")
        if len(parts) != 2:
            return None
        start_str, end_str = parts
        start = datetime.strptime(start_str.strip(), "%H:%M").time()
        end = datetime.strptime(end_str.strip(), "%H:%M").time()
        return start, end
    except Exception as e:
        logger.error(f"Fehler beim Parsen des Zeitbereichs {time_range}: {e}")
        return None

def compute_overlap(range1: str, range2: str) -> Optional[Tuple[time, time]]:
    """
    Berechnet den Überlappungszeitraum zwischen zwei Zeitbereichen (als Strings im Format "HH:MM-HH:MM").
    Gibt ein Tuple (overlap_start, overlap_end) als datetime.time-Objekte zurück, wenn ein Überlapp vorhanden ist, sonst None.
    """
    t1 = parse_time_range(range1)
    t2 = parse_time_range(range2)
    if not t1 or not t2:
        return None
    # Wähle das spätere Startzeitpunkt und das frühere Ende
    overlap_start = max(t1[0], t2[0])
    overlap_end = min(t1[1], t2[1])
    # Um sicherzustellen, dass ein gültiger Überlapp besteht, muss overlap_start < overlap_end sein.
    if overlap_start < overlap_end:
        return overlap_start, overlap_end
    return None

def generate_weekend_dates(start: datetime, period_days: int = 30) -> List[datetime]:
    """
    Generiert eine Liste von Datumsobjekten, die an Wochenendtagen (Samstag und Sonntag) zwischen 'start' und 'start + period_days' liegen.
    """
    dates = []
    end_date = start + timedelta(days=period_days)
    current = start
    while current <= end_date:
        if current.weekday() in (5, 6):  # Samstag: 5, Sonntag: 6
            dates.append(current)
        current += timedelta(days=1)
    return dates

def update_affected_matches(team_name: str) -> List[str]:
    """
    Aktualisiert alle Matches im gespeicherten Spielplan, die das angegebene Team betreffen.
    Dabei wird für jedes betroffene Match der Überlappungszeitraum neu berechnet.
    Falls kein Überlapp mehr vorhanden ist, wird das Match entfernt.
    Gibt eine Liste der betroffenen Spieler (Discord-Mentions) zurück.
    
    :param team_name: Der Name des Teams, dessen geänderte Verfügbarkeit Matches beeinflusst.
    :return: Liste von betroffenen Spieler-Mentions.
    """
    tournament = load_tournament_data()
    schedule = tournament.get("schedule", [])
    teams = tournament.get("teams", {})
    
    if team_name not in teams:
        logger.info(f"Team {team_name} ist nicht in den Turnierdaten vorhanden.")
        return []
    
    affected_members = set()
    updated_schedule = []
    
    for match in schedule:
        if match.get("team1") == team_name or match.get("team2") == team_name:
            # Bestimme das andere Team
            other_team = match["team2"] if match["team1"] == team_name else match["team1"]
            avail_team = teams.get(team_name, {}).get("verfügbarkeit", "")
            avail_other = teams.get(other_team, {}).get("verfügbarkeit", "")
            new_overlap = compute_overlap(avail_team, avail_other)
            if new_overlap:
                new_start = new_overlap[0].strftime("%H:%M")
                match["start_time"] = new_start
                updated_schedule.append(match)
                # Füge alle Mitglieder beider Teams hinzu
                for mem in teams.get(team_name, {}).get("members", []):
                    affected_members.add(mem)
                for mem in teams.get(other_team, {}).get("members", []):
                    affected_members.add(mem)
                logger.info(f"Match {team_name} vs. {other_team} aktualisiert: neuer Start um {new_start}.")
            else:
                logger.info(f"Match {team_name} vs. {other_team} wird entfernt, da kein Überlapp vorhanden ist.")
                # Überspringe das Match (d.h. es wird nicht in den neuen Spielplan übernommen)
        else:
            updated_schedule.append(match)
    
    tournament["schedule"] = updated_schedule
    save_tournament_data(tournament)
    return list(affected_members)

def schedule_round_robin_matches(teams: Dict[str, dict],
                                 start: datetime,
                                 period_days: int = 30) -> List[Dict]:
    """
    Erzeugt einen Spielplan (Round Robin) für alle Teams, die in 'teams' enthalten sind.
    Jedes Team wird gegen jedes andere Team gematcht – es wird versucht, für jedes Spiel einen Termin
    auf einen Wochenendtag innerhalb des angegebenen Zeitraums zu finden, und als Spielzeit wird der Beginn
    des Überlappungszeitraums der beiden Verfügbarkeiten gewählt.
    
    :param teams: Dictionary, in dem die Schlüssel die Teamnamen sind und der Wert ein Dictionary mit mindestens 
                  dem Schlüssel "verfugbarkeit" (z.B. "12:00-18:00") ist.
    :param start: Start-Datum, ab dem Termin generiert werden.
    :param period_days: Zeitfenster in Tagen (z.B. 30).
    :return: Liste von Match-Plan-Einträgen, z. B. [{"team1": "Team 1", "team2": "Team 2", "date": <datetime>, "start_time": "HH:MM"}, ...]
    """
    # Erzeuge alle mögliche Team-Paare (Round Robin)
    team_names = list(teams.keys())
    matches = []
    n = len(team_names)
    for i in range(n):
        for j in range(i + 1, n):
            team1 = team_names[i]
            team2 = team_names[j]
            # Ermittle die gemeinsamen Verfügbarkeiten:
            verf1 = teams[team1].get("verfügbarkeit", "")
            verf2 = teams[team2].get("verfügbarkeit", "")
            overlap = compute_overlap(verf1, verf2)
            if not overlap:
                # Wenn kein Überlapp vorhanden ist, kann man entweder diesen Match überspringen oder einen Standardzeitraum wählen.
                logger.info(f"Kein Überlapp für {team1} und {team2} zwischen {verf1} und {verf2}. Match wird übersprungen.")
                continue
            # Wähle als Startzeitpunkt des Matches den Beginn des Überlappungszeitraums
            match_time = overlap[0].strftime("%H:%M")
            matches.append({
                "team1": team1,
                "team2": team2,
                "match_time": match_time
            })
    
    # Generiere alle möglichen Spieltermine an Wochenenden innerhalb des Zeitraums
    weekend_dates = generate_weekend_dates(start, period_days)
    if not weekend_dates:
        logger.error("Keine Wochenendtermine im angegebenen Zeitraum gefunden.")
        return []
    
    # Weise den Matches Termine zu:
    # Falls mehr Matches als Termine vorhanden sind, wiederhole die Termine (oder plane mehrere Matches pro Termin)
    schedule = []
    total_dates = len(weekend_dates)
    for idx, match in enumerate(matches):
        date = weekend_dates[idx % total_dates]  # Wiederhole Terminauswahl, wenn nötig
        match_entry = {
            "team1": match["team1"],
            "team2": match["team2"],
            "date": date.strftime("%d.%m.%Y"),
            "start_time": match["match_time"]
        }
        schedule.append(match_entry)
    
    return schedule

def run_matchmaker() -> List[Dict]:
    """
    Führt den Matchmaker für Round-Robin-Matches aus, indem alle Teams aus tournament.json geladen werden.
    Dabei werden nur Teams berücksichtigt, für die ein Verfügbarkeitszeitraum (verfugbarkeit) hinterlegt wurde.
    Der Spielplan wird nur für Wochenendtermine innerhalb des nächsten Monats generiert.
    
    :return: Liste von Spielplan-Einträgen.
    """
    tournament = load_tournament_data()
    teams = tournament.get("teams", {})
    # Für das Matchmaking erwarten wir, dass jedes Team einen Verfügbarkeitszeitraum unter "verfugbarkeit" besitzt.
    # Falls ein Team keinen Zeitraum hat, können wir es entweder ausschließen oder mit einem Standardwert versehen.
    # Hier filtern wir Teams, die einen Eintrag haben:
    valid_teams = {team: data for team, data in teams.items() if data.get("verfügbarkeit")}
    if len(valid_teams) < 2:
        logger.info("Nicht genügend Teams mit Verfügbarkeitsangaben für das Matchmaking.")
        return []
    
    start_date = datetime.now()
    schedule = schedule_round_robin_matches(valid_teams, start_date, period_days=30)
    return schedule