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

## 🧠 Geplante Erweiterungen

### 📦 Version 2 – Fokus: Stabilität & Kernfeatures

- [ ] **1h vor Match Benachrichtigung**  
  Spieler erhalten automatisch eine Erinnerung an ihr anstehendes Match.

- [ ] **/request_reschedule – Matches verschieben**  
  Spieler können eine einmalige Anfrage zum Matchverschieben stellen, die vom Gegner bestätigt werden muss.

- [ ] **/update_availability – Verfügbarkeit ändern**  
  Teilnehmer können ihre Spielzeiten nachträglich anpassen. Der Matchplan wird intelligent aktualisiert.

- [ ] **Reminder mit @Mention**  
  Erinnerungen mentionen die betroffenen Spieler direkt im Chat.

- [ ] **Handling bei No-Shows**  
  Moderatoren können Matches als "Nicht angetreten" markieren.

- [ ] **Maximale Reschedules**  
  Schutz vor Missbrauch – nur 1 erlaubte Verschiebung pro Match.

- [ ] **/next_matches Command**  
  Zeigt Spielern ihre nächsten geplanten Matches kompakt an.

---

### 🚀 Version 3 – Fokus: Komfort & Flexibilität

- [ ] **Dynamische Teamgrößen (1vs1, 2vs2, 3vs3)**  
  Unterschiedliche Teamgrößen je Turnier möglich.

- [ ] **Mehrstufige Match-Verwaltung (Best-of-3, Finale, etc.)**  
  Unterstützung für Best-of-Formate und spezielle Finalrunden.

- [ ] **Live-Scoreboard während des Turniers**  
  Turnierergebnisse in Echtzeit sichtbar.

- [ ] **Fortgeschrittene Rescheduling-Logik**  
  Bei Terminänderungen automatische neue Vorschläge.

- [ ] **Smartes Balancing bei Ausfällen**  
  Dynamisches Anpassen des Spielplans, wenn ein Spieler ausfällt.

---

### 🌟 Version 4 – Fokus: Community & Luxus

- [ ] **Web-Dashboard für Matches und Leaderboards**  
  Schicke Browser-Oberfläche für Spieler, Zuschauer und Admins.

- [ ] **Serverübergreifende Statistiken**  
  Turniererfolge getrennt nach Discord-Server verwalten.

- [ ] **Turnierhistorie mit Archivfunktion**  
  Überblick über vergangene Turniere, Sieger und Statistiken.

- [ ] **Trophäensystem und Belohnungen**  
  Spieler erhalten Awards für Meilensteine (z.B. 3 Turniersiege).

- [ ] **Automatisierte Siegerehrung**  
  Nach Turnierende werden Rollen oder Titel automatisch verteilt.

---

## ✅ Bonusideen

- [ ] **Playoff- oder K.O.-System nach Gruppenphase**  
- [ ] **Integration von Preisgeldern oder Spiele-Keys**  
- [ ] **Internationale Zeitzonenunterstützung**  
- [ ] **Custom Matchregeln pro Turnier (z.B. Map-Pools, Sonderregeln)**

---

# 📋 Zusammenfassung

| Phase  | Ziel                  | Geplante Features                             |
|:-------|:----------------------|:----------------------------------------------|
| **V2** | Stabiler Turnierablauf | Erinnerungen, Reschedules, Verfügbarkeiten    |
| **V3** | Komfort & Erweiterungen | Dynamische Teams, Bo3, Live-Scoreboard       |
| **V4** | Community Features     | Web-Dashboard, Archiv, Preise & Awards        |

---

# 🤝 Contributing

Du hast eine coole Idee für **HeroldBot** oder möchtest helfen?  
> **Melde dich gerne oder öffne ein Issue! 🚀**

---

## 🧡 Credits

- [discord.py](https://discordpy.readthedocs.io/en/stable/) – Python Discord API Wrapper
- [python-dotenv](https://pypi.org/project/python-dotenv/) – Sicheres Management von Umgebungsvariablen

---

## 📜 Lizenz

Dieses Projekt steht unter der [MIT License](LICENSE).


