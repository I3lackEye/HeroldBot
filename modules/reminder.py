# modules/reminder.py

import asyncio
import os
from datetime import datetime, timedelta, timezone


from discord import TextChannel

from modules.dataStorage import load_tournament_data, save_tournament_data, REMINDER_ENABLED
from modules.embeds import send_match_reminder

# Lokale Module
from modules.logger import logger

REMINDER_PING = os.getenv("REMINDER_PING", "0") == "1"


from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import asyncio
from discord import TextChannel
from modules.dataStorage import load_tournament_data, save_tournament_data
from modules.embeds import send_match_reminder
from modules.logger import logger

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from discord import TextChannel
from modules.dataStorage import load_tournament_data, save_tournament_data, REMINDER_ENABLED
from modules.embeds import send_match_reminder
from modules.logger import logger

async def match_reminder_loop(channel: TextChannel):
    """
    Hintergrund-Task, der regelmäßig überprüft, ob bald Matches starten
    und Erinnerungen verschickt – nur wenn REMINDER_ENABLED aktiv ist.
    """
    await asyncio.sleep(5)  # kleine Verzögerung beim Start

    while True:
        if not REMINDER_ENABLED:
            logger.debug("[REMINDER] Reminder-System deaktiviert – überspringe Loop.")
            await asyncio.sleep(300)
            continue

        tournament = load_tournament_data()
        matches = tournament.get("matches", [])
        now = datetime.now(timezone.utc)

        for match in matches:
            scheduled_time_str = match.get("scheduled_time")
            reminder_sent = match.get("reminder_sent", False)

            if not scheduled_time_str or reminder_sent:
                continue

            try:
                scheduled_time = datetime.fromisoformat(scheduled_time_str)
                if scheduled_time.tzinfo is None:
                    scheduled_time = scheduled_time.replace(tzinfo=timezone.utc)
            except ValueError:
                logger.warning(f"[REMINDER] ❌ Ungültiges Zeitformat bei Match {match.get('match_id')}: {scheduled_time_str}")
                continue

            reminder_time = scheduled_time - now

            delta_str = str(reminder_time).split('.')[0].replace("days, ", "Tage, ")
            logger.debug(f"[REMINDER] Match {match.get('match_id')} geplant für {scheduled_time.strftime('%Y-%m-%d %H:%M:%S')} (UTC), jetzt: {now.strftime('%Y-%m-%d %H:%M:%S')} ➝ reminder_time = {delta_str}")

            if timedelta(0) < reminder_time <= timedelta(hours=1):
                logger.debug(f"[REMINDER] ➤ Reminder fällig für Match {match.get('match_id')}")

                # Platzhalter vorbereiten
                placeholders = {
                    "match_id": match.get("match_id", "???"),
                    "team1": match.get("team1", "Team 1"),
                    "team2": match.get("team2", "Team 2"),
                    "time": scheduled_time.astimezone(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y %H:%M"),
                }

                # Mentions direkt vorbereiten
                members1 = tournament.get("teams", {}).get(match.get("team1", ""), {}).get("members", [])
                members2 = tournament.get("teams", {}).get(match.get("team2", ""), {}).get("members", [])
                placeholders["mentions"] = " ".join(members1 + members2)

                try:
                    await send_match_reminder(channel, placeholders)
                    match["reminder_sent"] = True  # nur bei Erfolg
                    # Klarer Log für normale Nutzung
                    logger.info(f"[REMINDER] ✅ Reminder gesendet für Match {match.get('match_id')} – {placeholders['team1']} vs {placeholders['team2']} um {placeholders['time']}")

                    # Optional zusätzlich debuggen:
                    logger.debug(f"[REMINDER] ➤ reminder_time war: {str(reminder_time).split('.')[0]}")

                except Exception as e:
                    logger.error(f"[REMINDER] ❌ Fehler beim Senden des Reminders für Match {match.get('match_id')}: {e}")

            else:
                if reminder_time.total_seconds() < 0:
                    logger.debug(f"[REMINDER] Match {match.get('match_id')} ist bereits beendet. Kein Reminder mehr nötig.")
                else:

                    clean_time = str(reminder_time).split('.')[0].replace("days, ", "Tage, ")
                    logger.debug(f"[REMINDER] Match {match.get('match_id')} startet in {clean_time} – Reminder nicht gesendet (noch zu früh).")

        save_tournament_data(tournament)
        await asyncio.sleep(300)  # alle 5 Minuten prüfen


