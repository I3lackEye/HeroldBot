# 🛡️ HeroldBot

> Dein zuverlässiger Assistent für die Organisation und Verwaltung von Discord-Turnieren.

---

## 🛠️ Funktionen

- 🗳️ **Abstimmungen & Spielauswahl**: Umfragen mit Emoji-Reaktionen zur Wahl des Turnierspiels
- 📥 **Solo- & Team-Anmeldung**: Anmeldung mit Verfügbarkeiten und Blockiertagen
- 🎮 **Automatisches Matchmaking**:
  - Intelligente Paarung von Solo-Spielern
  - Erstellung von Round-Robin-Spielplänen
  - Verfügbarkeitsbasierte Slot-Zuweisung mit Pausenregelung
- 🔄 **Reschedule-System**:
  - Slash-Befehl für Matchverschiebung
  - Dynamische Slot-Suche & Turnierverlängerung
  - Abstimmung über neue Termine per Buttons
- 🔔 **Match-Reminder**:
  - Automatische Erinnerungen 1h vor Matchbeginn
  - Mentions der betroffenen Spieler
- 📊 **Statistiken & MVP-Auswertung**:
  - Siege, Teilnahmen, Lieblingsspiel, Winrate
  - Globales MVP-Ranking und Turnier-Historie
- 📦 **Turnierarchiv & Export**:
  - Abschluss-Backups und JSON-Archiv
  - ZIP-Export via DM
- 🧠 **Intelligente Autocomplete-Eingaben** bei IDs, Teams und Zeitfenstern
- 🧪 **Entwickler-Tools**:
  - Simuliere ganze Testdurchläufe
  - Diagnose aller Channel, Rollen & Tasks
- 🛡️ **Admin-Tools**:
  - Manuelles Eintragen von Siegen
  - Force-Abmeldungen
  - Direktes Starten & Beenden von Turnieren
  - Spielverwaltung (Add/Remove)
  - Dynamischer /stop-Befehl zur sicheren Beendigung

---

## 🚀 Installation

```bash
git clone https://github.com/dein-benutzername/HeroldBot.git
cd HeroldBot
python3.13 -m venv .venv
source .venv/bin/activate  # oder .venv\Scripts\activate auf Windows
pip install -r requirements.txt
```

---

## ⚙️ Konfiguration

- `.env` Datei anlegen (siehe `.env.example`)
- `config.json` anpassen (Pfadangaben, Rollen, Channels etc.)
- Embeds & Texte in `/configs/` bzw. `/locale/` editieren
- Sprachpakete für `de` und `en` verfügbar (einfach erweiterbar)

---

## 📚 Slash-Commands Übersicht

### 🧍 Anmeldung & Verfügbarkeit
- `/player join` – Anmelden (Solo oder mit Partner)
- `/player leave` – Vom Turnier abmelden
- `/player update_availability` – Verfügbarkeiten aktualisieren
- `/player participants` – Zeigt aktuelle Teilnehmer

### 📜 Turnierinfos
- `/info help` – Übersicht der Bot-Befehle
- `/info match_schedule` – Aktueller Spielplan
- `/info team` – Zeigt eigenes Team & Verfügbarkeit
- `/info list_games` – Wählbare Spiele anzeigen

### 🔄 Matchorganisation
- `/player request_reschedule` – Matchverschiebung beantragen
- `/test_reminder` – Reminder manuell testen (nur Dev)

### 📊 Statistiken
- `/stats stats` – Eigene oder fremde Stats anzeigen
- `/stats overview` – Bestenliste, Turnierübersicht, Match-Historie
- `/stats status` – Aktueller Zustand des Turniers

### 🛡️ Admin & Dev
- `/admin start_tournament` – Neues Turnier starten (mit Modal)
- `/admin end_tournament` – Turnier beenden & archivieren
- `/admin close_registration` – Anmeldung manuell schließen
- `/admin archive_tournament` – Turnier archivieren
- `/admin sign_out` – Spieler zwangsweise abmelden
- `/admin add_win` – Sieg manuell vergeben
- `/admin award_overall_winner` – Gesamtsieger eintragen
- `/admin manage_game` – Spiele verwalten (hinzufügen/löschen)
- `/admin end_poll` – Umfrage manuell beenden
- `/admin reload` – Slash-Commands neu laden
- `/admin reset_reschedule` – Reschedule-Anfrage zurücksetzen
- `/admin export_data` – Turnierdaten als ZIP exportieren (DM)
- `/dev simulate_full_flow` – Kompletten Testdurchlauf starten
- `/dev diagnose` – Systemdiagnose (Channel, Rollen, Tasks)
- `/dev stop` – Bot beenden (nur Dev)

---

## 🔐 Sicherheit

- `.env` niemals öffentlich machen!
- `.gitignore` schützt `.env`, `/data/`, `/backups/`, `/logs/` und Debug-Dateien
- Alle kritischen Adminfunktionen sind rollenbasiert geschützt

---

## 🛣️ Roadmap V3 (geplant)

- 🌀 Flexible Turniermodi (Double Elimination, Gruppenphase)
- 🌐 Mehrsprachigkeit & bessere Sprachumschaltung
- 📆 Benutzerdefinierte Spieltage & Blockzeiten
- 🎁 Key-Vergabe-System (für Gewinnspiele oder Belohnungen)
- 📅 Kalenderintegration (iCal-Export)
- 🧪 Unit Tests & CI/CD mit GitHub Actions

---

## ✨ Credits

- **BlackEye** – Code, Ideen, Kaffee

---

## 🔗 Ressourcen

- [discord.py auf GitHub](https://github.com/Rapptz/discord.py)
- [discord.py Doku](https://discordpy.readthedocs.io/en/stable/)
- [Python-Zoneninfos](https://docs.python.org/3/library/zoneinfo.html)
