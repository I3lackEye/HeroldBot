# modules/reminder.py

import asyncio
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from discord import TextChannel

from modules.config import CONFIG
from modules.dataStorage import load_tournament_data, save_tournament_data, REMINDER_ENABLED
from modules.embeds import send_match_reminder
from modules.logger import logger

REMINDER_PING = os.getenv("REMINDER_PING", "0") == "1"


async def match_reminder_loop(channel: TextChannel):
    """
    Background task that periodically checks if matches are starting soon
    and sends reminders – only when REMINDER_ENABLED is active.
    """
    await asyncio.sleep(5)  # small delay at start

    while True:
        if not REMINDER_ENABLED:
            logger.debug("[REMINDER] Reminder system disabled – skipping loop.")
            await asyncio.sleep(300)
            continue

        tournament = load_tournament_data()
        matches = tournament.get("matches", [])
        now = datetime.now(tz=ZoneInfo(CONFIG.bot.timezone))

        for match in matches:
            scheduled_time_str = match.get("scheduled_time")
            reminder_sent = match.get("reminder_sent", False)

            if not scheduled_time_str or reminder_sent:
                continue

            try:
                scheduled_time = datetime.fromisoformat(scheduled_time_str)
                if scheduled_time.tzinfo is None:
                    scheduled_time = scheduled_time.replace(tzinfo=ZoneInfo(CONFIG.bot.timezone))
            except ValueError:
                logger.warning(f"[REMINDER] ❌ Invalid time format for match {match.get('match_id')}: {scheduled_time_str}")
                continue

            reminder_time = scheduled_time - now

            delta_str = str(reminder_time).split('.')[0].replace("days, ", " days, ")
            logger.debug(f"[REMINDER] Match {match.get('match_id')} scheduled for {scheduled_time.strftime('%Y-%m-%d %H:%M:%S')} (UTC), now: {now.strftime('%Y-%m-%d %H:%M:%S')} ➝ reminder_time = {delta_str}")

            if timedelta(0) < reminder_time <= timedelta(hours=1):
                logger.debug(f"[REMINDER] ➤ Reminder due for match {match.get('match_id')}")

                # Prepare placeholders
                placeholders = {
                    "match_id": match.get("match_id", "???"),
                    "team1": match.get("team1", "Team 1"),
                    "team2": match.get("team2", "Team 2"),
                    "time": scheduled_time.astimezone(ZoneInfo(CONFIG.bot.timezone)).strftime("%d.%m.%Y %H:%M"),
                }

                # Prepare mentions directly
                members1 = tournament.get("teams", {}).get(match.get("team1", ""), {}).get("members", [])
                members2 = tournament.get("teams", {}).get(match.get("team2", ""), {}).get("members", [])
                placeholders["mentions"] = " ".join(members1 + members2)

                try:
                    await send_match_reminder(channel, placeholders)
                    match["reminder_sent"] = True  # only on success
                    # Clear log for normal usage
                    logger.info(f"[REMINDER] ✅ Reminder sent for match {match.get('match_id')} – {placeholders['team1']} vs {placeholders['team2']} at {placeholders['time']}")

                    # Optional additional debugging:
                    logger.debug(f"[REMINDER] ➤ reminder_time was: {str(reminder_time).split('.')[0]}")

                except Exception as e:
                    logger.error(f"[REMINDER] ❌ Error sending reminder for match {match.get('match_id')}: {e}")

            else:
                if reminder_time.total_seconds() < 0:
                    logger.debug(f"[REMINDER] Match {match.get('match_id')} is already finished. No reminder needed.")
                else:
                    clean_time = str(reminder_time).split('.')[0].replace("days, ", " days, ")
                    logger.debug(f"[REMINDER] Match {match.get('match_id')} starts in {clean_time} – Reminder not sent (too early).")

        save_tournament_data(tournament)
        await asyncio.sleep(300)  # check every 5 minutes
