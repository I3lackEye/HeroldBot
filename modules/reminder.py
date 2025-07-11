# modules/reminder.py

import asyncio
import os
from datetime import datetime, timedelta, timezone

from discord import TextChannel

from modules.dataStorage import load_tournament_data, save_tournament_data
from modules.embeds import send_match_reminder

# Lokale Module
from modules.logger import logger

REMINDER_PING = os.getenv("REMINDER_PING", "0") == "1"


async def match_reminder_loop(channel: TextChannel):
    """
    Hintergrund-Task, der regelmäßig überprüft, ob bald Matches starten
    und Erinnerungen verschickt.
    """
    await asyncio.sleep(5)  # kleine Verzögerung, damit Bot erstmal vollständig startet

    while True:
        tournament = load_tournament_data()
        matches = tournament.get("matches", [])
        now = now = datetime.now(timezone.utc)

        for match in matches:
            scheduled_time_str = match.get("scheduled_time")
            reminder_sent = match.get("reminder_sent", False)

            if not scheduled_time_str or reminder_sent:
                continue

            try:
                scheduled_time = datetime.strptime(scheduled_time_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                continue  # Falls Format mal abweicht

            # Reminder 1h vorher senden
            reminder_time = scheduled_time - now
            if timedelta(0) < reminder_time <= timedelta(hours=1):
                logger.debug(f"[REMINDER] reminder_time = {reminder_time} ({type(reminder_time)})")
                await send_match_reminder(channel, match)
                match["reminder_sent"] = True  # markieren
            else:
                logger.debug(
                    f"[REMINDER] Match {match.get('match_id')} startet in {reminder_time}. "
                    f"Reminder nicht gesendet (entweder zu früh oder zu spät)."
                )

        save_tournament_data(tournament)

        await asyncio.sleep(300)  # alle fünf Minute prüfen
