# matchmaker.py
import random
from .dataStorage import load_tournament_data, save_tournament_data

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
    # (Alternativ kannst du auch die Teams komplett ersetzen, je nach gewünschtem Verhalten)
    tournament["teams"].update(new_teams)
    # Aktualisiere die Solo-Liste. Falls ein Spieler übrig blieb, wird er beibehalten.
    tournament["solo"] = players
    save_tournament_data(tournament)
    return new_teams