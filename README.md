# HeroldBot

Ein leistungsstarker Discord-Turnierbot für die Organisation und Verwaltung von Community-Turnieren.  
Mit Features wie automatischem Matchmaking, Solo-/Team-Anmeldung, Umfragen, Leaderboards und Statistiken!

---

## 📋 Features

- ✅ Solo- und Team-Anmeldungen
- ✅ Automatisches Matchmaking nach Verfügbarkeit
- ✅ Dynamisches Poll-System zur Spielauswahl
- ✅ Spieler- und Turnier-Statistiken (Siege, Winrate, Lieblingsspiel)
- ✅ Leaderboard für motivierende Wettbewerbe
- ✅ Admin-Tools für Turnierverwaltung
- ✅ Umfangreicher Debug-Modus (optional aktivierbar)
- ✅ Sicherer Umgang mit Token und Konfigurationsdaten (.env basiert)

---

## 🚀 Installation

1. **Projekt klonen:**

- bash
- git clone https://github.com/dein-benutzername/HeroldBotV2.git
- cd HeroldBot

---

## Virtuelle Umgebung erstellen (optional, empfohlen):

- python -m venv .venv
- source .venv/bin/activate   # (Linux/macOS)
- .venv\Scripts\activate      # (Windows)

---

## Abhängigkeiten installieren:

pip install -r requirements.txt

---

## .env Datei erstellen:

Erstelle eine Datei .env im Hauptverzeichnis basierend auf .env.example:

DISCORD_TOKEN=hier-dein-token-einfügen
DEBUG=1
DATA_PATH=data.json
TOURNAMENT_PATH=tournament.json

---

## Bot starten

python -m scripts.bot

---

## ⚙️ Konfiguration

### Konfigurationsdateien:

| Datei            | Zweck |
|:-----------------|:------|
| `.env`            | Umgebungsvariablen wie Bot-Token, Debug-Status, Pfade |
| `config.json`     | Texte, Embed-Designs, Rollenzuweisungen |
| `data.json`       | Globale Spielerstatistiken (wird automatisch erzeugt) |
| `tournament.json` | Aktuelle Turnierdaten (wird automatisch erzeugt) |

---

## 🛡️ Sicherheitshinweis

- **Niemals** die `.env` Datei ins Repository committen.
- **Immer** `.env` in `.gitignore` eintragen.

---

## 🛠 Verfügbare Slash-Commands

| Befehl                | Beschreibung |
|:----------------------|:--------------|
| `/anmelden`            | Spieler für das Turnier anmelden |
| `/update_availability` | Verfügbarkeit aktualisieren |
| `/sign_out`            | Vom Turnier abmelden |
| `/participants`        | Liste der Teilnehmer anzeigen |
| `/leaderboard`         | Bestes Ranking anzeigen |
| `/stats <User>`        | Statistiken eines Spielers anzeigen |
| `/start_tournament`    | (Admin) Neues Turnier starten |
| `/end_tournament`      | (Admin) Turnier beenden |
| `/admin_abmelden`      | (Admin) Spieler zwangsabmelden |
| `/admin_add_win`       | (Admin) Siege manuell hinzufügen |
| `/add_game` / `/remove_game` | (Admin) Spiele für Polls verwalten |
| `/award_overall_winner` | (Admin) Turniersieg manuell vergeben |
| `/report_match`        | (User) Ergebnis eines Matches eintragen |

---

## 🏗️ ToDo / Ideen für die Zukunft

- Dynamische Teamgrößen (1vs1, 2vs2, 3vs3)
- Mehrstufige Match-Verwaltung (Best-of-3, Finals, etc.)
- Web-Dashboard (Statusanzeige, Matches, Leaderboards)
- Bessere Autocomplete-Features
- Serverübergreifende Statistiken
- Turnierhistorie mit Archivfunktion

---

## 🧡 Credits

- [discord.py](https://discordpy.readthedocs.io/en/stable/) – Python Discord API Wrapper
- [python-dotenv](https://pypi.org/project/python-dotenv/) – Sicheres Management von Umgebungsvariablen

---

## 📜 Lizenz

Dieses Projekt steht unter der [MIT License](LICENSE).


