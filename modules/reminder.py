# modules/reminder.py

import asyncio
from datetime import datetime, timedelta
from discord import TextChannel

# Lokale Module
from modules.logger import logger
from modules.dataStorage import load_tournament_data, save_tournament_data
from modules.embeds import send_match_reminder
from datetime import datetime, timezone


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
            if 0 < (scheduled_time - now) <= timedelta(hours=1):
                await send_match_reminder(channel, match)
                match["reminder_sent"] = True  # markieren

        save_tournament_data(tournament)

        await asyncio.sleep(300)  # alle fünf Minute prüfen