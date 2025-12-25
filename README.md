# 🛡️ HeroldBot

> Dein zuverlässiger Assistent für die Organisation und Verwaltung von Discord-Turnieren.

Ein robuster Discord-Bot für automatisierte Turnierverwaltung mit intelligenter Zeitplanung, Verfügbarkeitsmanagement und umfassenden Statistiken.

---

## ✨ Hauptmerkmale

### 🎯 Kernfunktionen
- 🗳️ **Spielauswahl per Abstimmung**: Emoji-Reaktions-Umfragen zur Wahl des Turnierspiels
- 📥 **Flexible Anmeldung**: Solo-Spieler oder fertige Teams mit individuellen Verfügbarkeiten
- 🎮 **Intelligentes Matchmaking**:
  - Automatische Paarung von Solo-Spielern basierend auf gemeinsamen Verfügbarkeiten
  - Round-Robin-Spielplanerstellung für faire Turniere
  - Verfügbarkeitsbasierte Slot-Zuweisung mit intelligenter Pausenregelung
  - Rescue-Modus für schwer planbare Matches
- 🔄 **Flexibles Reschedule-System**:
  - Verschiebungsanfragen mit automatischer Slot-Suche
  - Abstimmung per Discord-Buttons (✅/❌)
  - Automatische Turnierverlängerung bei Bedarf
  - 24-Stunden-Timeout für Abstimmungen
- 🔔 **Automatische Erinnerungen**:
  - Match-Reminder 1 Stunde vor Spielbeginn
  - Direkte Erwähnung aller betroffenen Spieler
  - Kontinuierlicher Background-Loop
- 📊 **Umfassende Statistiken**:
  - Spieler: Siege, Teilnahmen, Lieblingsspiel, Winrate
  - Turnier: Match-Historie, MVP-Ranking, Gesamtsieger
  - Globale Bestenlisten und Turnierarchiv

### 🏗️ Technische Features
- ⚙️ **Modular Config System**: Getrennte Konfigurationsdateien für Bot, Turnier und Features
- 💾 **Atomic File Writes**: Datensicherheit auch bei Abstürzen
- 🔐 **Rollenbasierte Berechtigungen**: Admin, Moderator, Developer-Rollen
- 🌍 **Mehrsprachigkeit**: Deutsch/Englisch mit lokalisierten Embeds
- 🕒 **Timezone-Aware**: Korrekte Zeitverarbeitung mit ZoneInfo
- 📦 **Automatische Backups**: Turnierarchiv mit JSON und ZIP-Export
- 🧪 **Umfangreiche Dev-Tools**: Dummy-Generatoren, Diagnose, Testszenarien
- 🛡️ **Robuste Error-Handling**: Graceful degradation bei Fehlern
- 📝 **Typed Configuration**: Type-safe Config mit Python Dataclasses

---

## 🚀 Installation

### Voraussetzungen
- Python 3.13+
- Discord Bot Token ([Discord Developer Portal](https://discord.com/developers/applications))
- Server mit aktivierten Privileged Gateway Intents (Members, Message Content)

### Setup

```bash
# Repository klonen
git clone https://github.com/I3lackEye/HeroldBot.git
cd HeroldBot

# Virtual Environment erstellen
python3.13 -m venv .venv
source .venv/bin/activate  # oder .venv\Scripts\activate auf Windows

# Dependencies installieren
pip install -r requirements.txt

# Umgebungsvariablen konfigurieren
cp .env.example .env
# .env editieren und TOKEN eintragen

# Bot starten
python modules/main.py
```

---

## ⚙️ Konfiguration

### Konfigurationsdateien

#### **`.env`** – Sensible Daten (niemals committen!)
```env
TOKEN=dein_discord_bot_token_hier
DEBUG_MODE=False
REMINDER_ENABLED=True
```

#### **`configs/bot.json`** – Bot-Einstellungen
```json
{
  "data_paths": {
    "data": "data/data.json",
    "tournament": "data/tournament.json"
  },
  "channels": {
    "limits": "CHANNEL_ID",
    "reminder": "CHANNEL_ID",
    "reschedule": "CHANNEL_ID"
  },
  "roles": {
    "moderator": ["Moderator", "1234567890"],
    "admin": ["Admin"],
    "dev": ["Developer", "1234567890"],
    "winner": ["Champion"]
  },
  "language": "de",
  "timezone": "Europe/Berlin",
  "max_string_length": 50
}
```

#### **`configs/tournament.json`** – Turnier-Parameter
```json
{
  "match_duration_minutes": 90,
  "pause_duration_minutes": 30,
  "max_time_budget_hours": 2,
  "reschedule_timeout_hours": 24,
  "slot_interval_minutes": 60,
  "active_days": {
    "friday": {"start": "16:00", "end": "22:00"},
    "saturday": {"start": "10:00", "end": "22:00"},
    "sunday": {"start": "10:00", "end": "22:00"}
  }
}
```

#### **`configs/features.json`** – Feature-Toggles
```json
{
  "enable_auto_match_solo": true,
  "enable_reminder": true,
  "enable_reschedule": true
}
```

### Sprachpakete
- Embeds und Texte in `/locale/{language}/embeds/`
- Teamname-Generator in `/locale/{language}/names_{language}.json`
- Unterstützt: `de`, `en` (einfach erweiterbar)

---

## 📚 Slash-Commands Übersicht

### 🧍 Anmeldung & Verfügbarkeit
| Command | Beschreibung |
|---------|-------------|
| `/player join` | Anmelden (Solo oder mit Partner via Modal) |
| `/player leave` | Vom Turnier abmelden |
| `/player update_availability` | Verfügbarkeiten aktualisieren |
| `/player participants` | Aktuelle Teilnehmerliste anzeigen |

### 📜 Turnierinfos
| Command | Beschreibung |
|---------|-------------|
| `/info help` | Übersicht aller Bot-Befehle |
| `/info match_schedule` | Aktueller Spielplan mit Zeitangaben |
| `/info team` | Eigenes Team & Verfügbarkeit anzeigen |
| `/info list_games` | Verfügbare Spiele anzeigen |

### 🔄 Matchorganisation
| Command | Beschreibung |
|---------|-------------|
| `/player request_reschedule` | Matchverschiebung beantragen (mit Abstimmung) |
| `/test_reminder` | Match-Reminder manuell testen (nur Dev) |

### 📊 Statistiken
| Command | Beschreibung |
|---------|-------------|
| `/stats stats` | Eigene oder fremde Statistiken anzeigen |
| `/stats overview` | Bestenliste, Turnierübersicht, Match-Historie |
| `/stats status` | Aktueller Turnierstatus (Teams, Matches, Zeitplan) |

### 🛡️ Admin-Befehle
| Command | Beschreibung |
|---------|-------------|
| `/admin start_tournament` | Neues Turnier starten (Modal mit Zeitangaben) |
| `/admin end_tournament` | Turnier beenden & archivieren |
| `/admin close_registration` | Anmeldung manuell schließen |
| `/admin archive_tournament` | Turnier in Archiv verschieben |
| `/admin sign_out` | Spieler/Team zwangsweise abmelden |
| `/admin add_win` | Sieg manuell vergeben |
| `/admin award_overall_winner` | Gesamtsieger festlegen |
| `/admin manage_game` | Spiele hinzufügen/entfernen |
| `/admin end_poll` | Spielauswahl-Umfrage manuell beenden |
| `/admin reload` | Slash-Commands neu synchronisieren |
| `/admin reset_reschedule` | Reschedule-Anfrage zurücksetzen |
| `/admin export_data` | Turnierdaten als ZIP exportieren (per DM) |

### 🧪 Developer-Tools
| Command | Beschreibung |
|---------|-------------|
| `/dev simulate_full_flow` | Kompletten Turnierdurchlauf simulieren |
| `/dev generate_dummy` | Testdaten generieren (6 Szenarien: easy, hard, blocked, mixed, realistic, custom) |
| `/dev reset_tournament` | Turnierdaten auf Standard zurücksetzen |
| `/dev show_state` | Aktuellen Turnierstatus detailliert anzeigen |
| `/dev test_matchmaker` | Matchmaker-Algorithmus testen (Dry-Run) |
| `/dev generate_matches` | Matches generieren und zuweisen |
| `/dev diagnose` | Systemdiagnose (Channel, Rollen, Tasks, Config) |
| `/dev stop` | Bot sicher herunterfahren |

---

## 🏗️ Projektstruktur

```
HeroldBot/
├── modules/
│   ├── main.py              # Bot-Einstiegspunkt mit Error-Handling
│   ├── config.py            # Zentrales Config-Management (NEW)
│   ├── dataStorage.py       # Datenpersistenz mit Atomic Writes
│   ├── matchmaker.py        # Matchmaking & Scheduling-Algorithmen
│   ├── players.py           # Anmeldung & Verfügbarkeiten
│   ├── tournament.py        # Turnier-Lifecycle-Management
│   ├── stats.py             # Statistiken & Rankings
│   ├── embeds.py            # Discord-Embed-Templates
│   ├── admin_tools.py       # Admin-Kommandos
│   ├── dev_tools.py         # Developer-Utilities
│   ├── info.py              # Info-Commands
│   ├── reminder.py          # Match-Reminder-System
│   ├── reschedule.py        # Reschedule-Logic
│   ├── poll.py              # Spielauswahl-Abstimmungen
│   ├── archive.py           # Turnier-Archivierung
│   ├── logger.py            # Logging-Setup
│   ├── utils.py             # Helper-Funktionen
│   └── task_manager.py      # Background-Task-Verwaltung
├── configs/
│   ├── bot.json             # Bot-Konfiguration
│   ├── tournament.json      # Turnier-Parameter
│   └── features.json        # Feature-Flags
├── locale/
│   ├── de/embeds/           # Deutsche Embed-Templates
│   ├── en/embeds/           # Englische Embed-Templates
│   └── {lang}/names_{lang}.json  # Teamname-Generatoren
├── data/
│   ├── data.json            # Globale Spielerdaten & Stats
│   ├── tournament.json      # Aktuelles Turnier
│   └── games.json           # Verfügbare Spiele
├── views/                   # Discord UI Components (Buttons, Modals)
├── backups/                 # Automatische Backups
├── archive/                 # Archivierte Turniere
├── logs/                    # Log-Dateien
├── .env                     # Umgebungsvariablen (nicht versioniert)
├── .gitignore              # Git-Ignore-Rules
├── requirements.txt         # Python-Dependencies
└── README.md               # Diese Datei
```

---

## 🔐 Sicherheit

- ✅ `.env` niemals öffentlich machen oder committen!
- ✅ `.gitignore` schützt `.env`, `/data/`, `/backups/`, `/logs/` und `__pycache__/`
- ✅ Alle Admin-Funktionen sind rollenbasiert geschützt
- ✅ Atomic File Writes verhindern Datenverlust bei Crashes
- ✅ Input-Validierung für alle User-Eingaben
- ✅ Automatische Backups vor kritischen Operationen

---

## 🧠 Intelligente Features im Detail

### Verfügbarkeitsbasiertes Matchmaking
1. **Slot Matrix Generation**: Erstellt globale Zeitfenster basierend auf Teamverfügbarkeiten
2. **Overlap Detection**: Findet optimale Spielzeiten für beide Teams
3. **Pause Enforcement**: Garantiert Mindestpausen zwischen Matches
4. **Time Budget Tracking**: Verhindert Überlastung einzelner Spieltage
5. **Rescue Mode**: Weist schwierige Matches mit relaxierten Regeln zu

### Solo-Player Auto-Matching
- Merged Verfügbarkeiten von Solo-Spielern
- Nur Teams mit echtem Zeitüberschnitt werden erstellt
- Automatische Team-Namen-Generierung aus Wörterbuch
- Orphan-Team-Cleanup bei ungeraden Spielerzahlen

### Reschedule-System
- Findet automatisch freie Slots nach Turnierende
- Verlängert Turnier bei Bedarf
- DM-Benachrichtigungen an alle betroffenen Spieler
- Button-basierte Abstimmung (Konsens erforderlich)
- 24h Timeout mit automatischer Ablehnung

---

## 🛣️ Roadmap V3 (geplant)

- 🌀 **Flexible Turniermodi**: Double Elimination, Swiss System, Gruppenphase
- 🎨 **Custom Themes**: Anpassbare Embed-Farben und -Designs
- 🌐 **Erweiterte Mehrsprachigkeit**: Weitere Sprachen, Runtime-Sprachumschaltung
- 📆 **Benutzerdefinierte Spieltage**: Flexiblere Turnierzeiträume
- 🎁 **Belohnungssystem**: Automatische Key-Vergabe für Gewinner
- 📅 **Kalenderintegration**: iCal-Export für Matches
- 🧪 **Unit Tests & CI/CD**: Automatisierte Tests mit GitHub Actions
- 📈 **Analytics Dashboard**: Webinterface für Turnier-Insights
- 🔗 **API**: REST-API für externe Integrationen
- 🤖 **AI-Features**: Intelligente Spieler-Empfehlungen, automatische Konfliktlösung

---

## 📊 Technische Details

### Dependencies
- **discord.py**: Discord Bot-Framework
- **python-dotenv**: Umgebungsvariablen-Management
- **typing**: Type Hints und Annotations
- **zoneinfo**: Timezone-Aware Datetime-Handling
- **json**: Konfiguration und Datenspeicherung
- **asyncio**: Asynchrone Background-Tasks

### Performance
- Atomic File Operations für Datensicherheit
- Lazy Loading von Konfigurationen
- Caching von häufig genutzten Daten
- Effiziente Slot-Matrix-Generierung
- Background-Tasks für nicht-blockierende Operationen

### Error Handling
- Globale Event-Error-Handler
- Slash-Command-Error-Handler mit User-Feedback
- Graceful Degradation bei Teilausfällen
- Comprehensive Logging für Debugging
- Validation auf allen Eingabeebenen

---

## 🤝 Contributing

Contributions sind willkommen! Bitte:
1. Fork das Repository
2. Erstelle einen Feature-Branch (`git checkout -b feature/AmazingFeature`)
3. Committe deine Änderungen (`git commit -m 'Add some AmazingFeature'`)
4. Push zum Branch (`git push origin feature/AmazingFeature`)
5. Öffne einen Pull Request

---

## ✨ Credits

- **I3lackEye** – Entwicklung, Architektur, Kaffeekonsum
- **discord.py Community** – Exzellente Dokumentation und Support

---

## 📄 Lizenz

Dieses Projekt ist unter der MIT-Lizenz lizenziert.

---

## 🔗 Ressourcen

- [discord.py auf GitHub](https://github.com/Rapptz/discord.py)
- [discord.py Dokumentation](https://discordpy.readthedocs.io/en/stable/)
- [Python ZoneInfo](https://docs.python.org/3/library/zoneinfo.html)
- [Discord Developer Portal](https://discord.com/developers/applications)
- [Discord Privileged Intents](https://discord.com/developers/docs/topics/gateway#privileged-intents)

---

## 📞 Support

Bei Fragen oder Problemen:
- Öffne ein [GitHub Issue](https://github.com/I3lackEye/HeroldBot/issues)
- Kontaktiere I3lackEye

---

**Made with ❤️ and ☕ by I3lackEye**
