## 📘 Slash-Command Übersicht

### 🎮 Spielerbefehle

| Befehl | Beschreibung | Parameter | Zugriff |
|--------|--------------|-----------|---------|
| `/anmelden` | Meldet dich für das Turnier an (Solo oder im Team) | `verfugbarkeit` (z. B. 12:00-18:00), optional: `mitspieler`, `teamname` | Alle |
| `/update_availability` | Aktualisiere deine Verfügbarkeit | `verfugbarkeit` (z. B. 12:00-18:00) | Alle |
| `/sign_out` | Meldet dich vom Turnier ab | – | Alle |
| `/participants` | Zeigt alle aktuellen Anmeldungen | – | Alle |
| `/status` | Zeigt aktuellen Status des Turniers (Teams, Solo-Spieler, Spielplan etc.) | – | Alle |

---

### 📊 Statistikbefehle

| Befehl | Beschreibung | Parameter | Zugriff |
|--------|--------------|-----------|---------|
| `/stats` | Zeigt persönliche Turnierstatistiken eines Spielers | `user` (Discord-Mitglied) | Alle |
| `/leaderboard` | Zeigt die Top-Spieler nach Siegen | – | Alle |
| `/tournament_stats` | Zeigt allgemeine Turnierstatistiken (z. B. bester Spieler, beliebtestes Spiel) | – | Alle |

---

### 🛠️ Admin-/Mod-Befehle

| Befehl | Beschreibung | Parameter | Rollen |
|--------|--------------|-----------|--------|
| `/start_tournament` | Startet ein neues Turnier und beginnt die Spielauswahl via Poll | optional: `duration_days` (Standard: 7 Tage) | Moderator/Admin |
| `/close_registration` | Beendet die Registrierung manuell und startet die Teambildung | – | Moderator/Admin |
| `/set_winner` | Setzt den Gewinner eines Matches | `team` (mit Autocomplete) | Moderator/Admin |
| `/end_tournament` | Beendet das Turnier, speichert den Sieger und zeigt ein Abschluss-Embed an | `teamname`, `player1`, optional: `player2`, optional: `points` | Moderator/Admin |
| `/award_overall_winner` | Verleiht dem globalen Siegerteam die Gewinnerrolle | – | Moderator/Admin |
| `/add_game` | Fügt ein neues Spiel zur verfügbaren Liste hinzu | `title` | Moderator/Admin (Channel-beschränkt) |

---

### 🧪 Debug/Helper (nur intern nutzen)

| Befehl | Beschreibung | Parameter | Rollen |
|--------|--------------|-----------|--------|
| `/admin_abmelden` | Entfernt einen Spieler manuell (auch aus Teams) | `user` (Autocomplete) | Moderator/Admin |

---

## ⚙️ Weitere Hinweise

- **Rollenberechtigungen** werden über `config.json` gesteuert (`ROLE_PERMISSIONS`)
- **Spielauswahl per Poll**: Bei Gleichstand wird zufällig zwischen den Spielen mit den meisten Stimmen gewählt
- **Statistiken** (Siege, Winrate, Lieblingsspiel) werden automatisch in `data.json` aktualisiert
- **Alle Embeds** sind über `config.json` anpassbar (`GLOBAL_STATS_EMBED`, `TOURNAMENT_ENDED_ANNOUNCEMENT`, ...)

---

## 💡 Zukünftige Features
- **Automatische Rollenvergabe**
- **Gamekeys** werden in separater Datei (verschlüsselt gespeichert)
- **Tournament History**
- **Automove** spieler werden automatisch in ihre Teamchannel gemoved
- **Event management** Bot startet automatische Events basierend auf scheduel

> Diese Doku wurde zuletzt aktualisiert am **17.04.2025**
