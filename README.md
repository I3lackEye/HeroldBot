Funktionen
1. Registrierung & Teilnehmerverwaltung

    Team Registration (/anmelden):
    Ermöglicht es zwei Spielern, sich gemeinsam als Team mit einem Teamnamen anzumelden. Dabei wird überprüft, dass kein Spieler mehrfach in einem Team oder in der Einzelspieler-Liste registriert ist.

    Solo Registration (/anmelden_solo):
    Einzelspieler können sich registrieren, um später einem Team zugeordnet zu werden.

    Deregistration (/abmelden):
    Ein Spieler kann sich abmelden. Falls er in einem Team registriert ist, wird das Team aufgelöst und der andere Spieler wird zur Einzelspieler-Liste hinzugefügt.

    Teilnehmerliste anzeigen (/teilnehmer):
    Zeigt die aktuelle Liste der angemeldeten Teams und Einzelspieler sowie die Gesamtzahl der Teilnehmer an.

    Team Shuffle (/team_shuffle):
    Teilt alle registrierten Einzelspieler zufällig in 2er-Teams ein. (Nur für berechtigte Nutzer)

    Team umbenennen (/team_umbenennen):
    Ermöglicht es Teammitgliedern, den Namen ihres Teams zu ändern.

2. Matchplanung & Turnierstruktur

    Round-Robin Scheduling:
    Die Funktion round_robin_schedule erstellt einen Round-Robin-Plan, in dem jedes Team einmal gegen jedes andere spielt. Bei ungerader Anzahl von Teams wird ein Platzhalter ("BYE") verwendet.

    Matches auf Wochenenden verteilen:
    Mit den Funktionen get_weekend_dates, reorder_matches und distribute_matches_over_weekends werden die generierten Matches auf alle Wochenendtage eines bestimmten Monats verteilt. Dabei wird versucht, dass ein Team nicht in zwei aufeinanderfolgenden Matches spielt.

3. Verfügbarkeitsmanagement & Terminvorschläge

    Set Availability (/set_availability):
    Teams können ihre Verfügbarkeiten als durch Komma getrennte Zeitintervalle (z. B. "16:00-18:00,20:00-22:00") eingeben. Die Eingabe wird geparst und validiert.

    Availability Helper Functions:

        parse_time_interval: Wandelt einen Zeitintervall-String in ein Tupel von datetime.time-Objekten um.

        get_overlap: Berechnet den Schnitt zweier Zeitintervalle.

        common_availability: Ermittelt die gemeinsamen Zeitfenster zwischen zwei Teams.

    Match Proposal (/propose_match):
    Basierend auf den Verfügbarkeiten von zwei Teams wird ein gemeinsamer Termin vorgeschlagen. Dabei werden alle Spieler der beteiligten Teams in einer Nachricht erwähnt, um die Bestätigung (via Emoji-Reaktion) anzufordern.

4. Punkte- und Leaderboardverwaltung

    Punkte vergeben (/punkte):
    Admins können einem Team Punkte gutschreiben.

    Punkte entfernen (/punkte_entfernen):
    Ermöglicht Admins, Punkte von einem Team oder Spieler zu entfernen.

    Punkte zurücksetzen (/punkte_reset):
    Setzt alle vergebenen Punkte auf 0 zurück.

    Leaderboard (/leaderboard):
    Zeigt eine Rangliste der Teams basierend auf den vergebenen Punkten. (Befehl ist auf einen bestimmten Kanal begrenzt.)

5. Datenpersistenz und Logging

    Datenpersistenz:
    Alle Anmeldungen, Teamdaten, Punkte, und Verfügbarkeiten werden in einer JSON-Datei gespeichert. Die Funktionen load_anmeldungen und save_anmeldungen kümmern sich um das Laden und Speichern dieser Daten.

    Logging:
    Der Bot nutzt das interne Discord-Logging sowie ein zusätzliches Logging für eigene Events. Alle Logs werden in der Datei debug.log abgelegt. Mit dem Befehl /test_log kann geprüft werden, ob das Logging funktioniert.

Setup und Konfiguration

    Umgebungsvariablen:

        TOKEN: Der Bot-Token von Discord.

        DATABASE_PATH: Pfad zur JSON-Datenbank, in der alle Anmeldungen und Turnierdaten gespeichert werden.

    Kanalbeschränkungen:
    Einige Befehle (z. B. Registrierung, Teilnehmerliste) sind auf bestimmte Kanäle beschränkt.

        LIMITED_CHANNEL_ID_1: Für Turnier-Registrierung und verwandte Befehle (z. B. /anmelden, /teilnehmer).

        LIMITED_CHANNEL_ID_2: Für das Leaderboard (/leaderboard).

    Berechtigungsprüfung:
    Befehle, die administrativen Zugriff erfordern, prüfen über die Funktion has_permission, ob der Nutzer entsprechende Rollen besitzt (z. B. "Moderator", "Lappen des Vertrauens").

Starten des Bots

Stelle sicher, dass alle erforderlichen Umgebungsvariablen gesetzt sind und alle Abhängigkeiten (wie discord.py) installiert sind. Starte den Bot dann mit:

python bot.py

Erweiterungsmöglichkeiten

    Automatische Erinnerung:
    Implementiere Erinnerungsfunktionen vor den Matches.

    Kalenderintegration:
    Exportiere den finalen Spielplan in einen externen Kalender (z. B. Google Calendar) oder stelle eine ICS-Datei zum Download bereit.

    Erweiterte Abstimmungslogik:
    Baue eine robustere Emoji-Abstimmung für die Terminbestätigung ein, inklusive Timeout-Mechanismen und Rückfallebenen.
