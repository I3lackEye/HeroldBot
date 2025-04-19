# 🛡️ HeroldBot

> Dein zuverlässiger Assistent für die Organisation und Verwaltung von Discord-Turnieren.

---

## 🛠️ Funktionen

- 🎮 Intelligente Match-Verteilung auf freie Slots
- 🔔 Automatische Erinnerungen an bevorstehende Matches
- 🔄 Reschedule-Anfragen per DM oder im Channel
- 🏆 MVP- und Bestenlisten-Tracking
- 📦 Vollständige Archivierung abgeschlossener Turniere
- 📈 Match- und Turnierstatistiken auf Knopfdruck
- 🛡️ Umfassende Admin-Tools für maximale Kontrolle

---

## 🚀 Installation

```
bash
git clone https://github.com/dein-benutzername/HeroldBot.git
cd HeroldBot
python3.13 -m venv .venv
source .venv/bin/activate  # oder .venv\Scripts\activate auf Windows
pip install -r requirements.txt
```

---

## ⚙️ Konfiguration

- Lege eine `.env` Datei an basierend auf `.env.example`.
- Passe die `config.json` an deine Bedürfnisse an.
- Embeds und Texte befinden sich in `/configs/` und können angepasst werden.
- Sprachpakete (Deutsch/Englisch) findest du unter `/langs/`.

---

## 📚 Slash-Commands Übersicht

### 📥 Anmeldung & Verfügbarkeit
- `/anmelden` – Spieler anmelden
- `/update_availability` – Verfügbarkeit aktualisieren
- `/sign_out` – Abmelden vom Turnier
- `/participants` – Teilnehmerliste anzeigen

### ❓ Hilfe
- `/help` – Übersicht aller verfügbaren Befehle

### 📜 Matchorganisation
- `/list_matches` – Alle geplanten Matches anzeigen
- `/request_reschedule` – Anfrage zur Matchverschiebung stellen
- `/test_reminder` – Testet einen Match-Reminder

### 📊 Statistiken
- `/leaderboard` – Bestenliste anzeigen
- `/stats` – Eigene Turnierstatistik abrufen
- `/tournament_stats` – Turnierstatistiken anzeigen
- `/status` – Statusübersicht des Turniers

### 🎮 Turniermanagement
- `/report_match` – Match-Ergebnis eintragen
- `/match_history` – Match-Historie anzeigen
- `/team_stats` – Teamstatistiken anzeigen
- `/match_schedule` – Spielplan anzeigen

### 🛡️ Adminbefehle
- `/admin_abmelden` – Spieler administrativ abmelden
- `/admin_add_win` – Spieler administrativ einen Sieg hinzufügen
- `/start_tournament` – Neues Turnier starten
- `/end_tournament` – Turnier abschließen
- `/add_game` – Spiel hinzufügen
- `/remove_game` – Spiel entfernen
- `/award_overall_winner` – Gesamtsieger auszeichnen
- `/reload_commands` – Slash-Commands neu laden
- `/close_registration` – Anmeldung schließen
- `/generate_dummy_teams` – Dummy-Teams generieren
- `/archive_tournament` – Turnier archivieren

---

## 🛡️ Sicherheitshinweis

- Speichere deine `.env` Datei niemals öffentlich ab!
- Nutze `.gitignore`, um sensible Daten zuverlässig auszuschließen.

---

## 🛣️ Roadmap V3 (geplant)

- 🌍 Mehrsprachige Unterstützung (erweiterte Sprachpakete)
- 🛡️ Erweiterte Turniermodi (Double Elimination etc.)
- 🎯 Voting-System für Sonderpreise
- 🛠️ Anpassbare Regeln pro Spiel
- 🏆 Saisonale Bestenlisten
- 🚀 Dynamische Slotgenerierung je nach Teilnehmerzahl

---

## ✨ Credits

- **BlackEye**

---

## 🔗 Weitere Ressourcen

- [discord.py auf GitHub](https://github.com/Rapptz/discord.py) – Offizielle Python-Bibliothek für Discord-Bots
- [discord.py Dokumentation](https://discordpy.readthedocs.io/en/stable/) – Ausführliche API-Dokumentation
