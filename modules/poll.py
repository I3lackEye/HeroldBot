# new_poll.py
import discord
import asyncio
import random
from discord.ext import commands
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Lokale Modules
from modules.dataStorage import load_tournament_data, save_tournament_data
from modules.logger import logger
from modules.embeds import send_poll_results, send_registration_open
from modules.tournament import auto_end_poll, close_registration_after_delay
from modules.task_manager import add_task

# Globale Variablen
poll_message_id = None
poll_channel_id = None
poll_votes = {}  # user_id -> emoji
poll_options = {}  # emoji -> spielname

emoji_list = ["🇦", "🇧", "🇨", "🇩", "🇪", "🇫", "🇬", "🇭", "🇮", "🇯"]

async def start_poll(channel: discord.TextChannel, options: list[str], registration_hours: int = 72, poll_duration_hours: int = 48):
    global poll_message_id, poll_channel_id, poll_votes, poll_options

    description = ""
    poll_options = {}

    for idx, option in enumerate(options):
        if idx >= len(emoji_list):
            break  # Nur so viele Emojis wie verfügbar
        emoji = emoji_list[idx]
        description += f"{emoji} {option}\n"
        poll_options[emoji] = option

    # Ablaufzeit berechnen
    poll_end_time = datetime.now(ZoneInfo("Europe/Berlin")) + timedelta(hours=registration_hours)
    poll_end_str = poll_end_time.strftime("%d.%m.%Y %H:%M Uhr")

    embed = discord.Embed(
        title="🎮 Abstimmung: Welches Spiel soll gespielt werden?",
        description=description,
        color=discord.Color.blue()
    )

    embed.set_footer(text=f"⏳ Abstimmung endet am: {poll_end_str}")

    message = await channel.send(embed=embed)

    for emoji in poll_options.keys():
        await message.add_reaction(emoji)

    poll_message_id = message.id
    poll_channel_id = message.channel.id
    poll_votes = {}
    logger.info(f"[POLL] Neue Abstimmung gestartet mit {len(options)} Optionen.")

async def end_poll(bot: discord.Client, channel: discord.TextChannel):
    global poll_message_id, poll_options

    if not poll_message_id:
        await channel.send("❌ Keine aktive Umfrage gefunden.")
        return

    try:
        message = await channel.fetch_message(poll_message_id)
    except Exception as e:
        logger.error(f"[POLL] Fehler beim Holen der Umfrage-Nachricht: {e}")
        await channel.send("❌ Fehler beim Holen der Umfrage-Nachricht.")
        return

    real_votes = {}

    for reaction in message.reactions:
        if str(reaction.emoji) in poll_options:
            async for user in reaction.users():
                if not user.bot:
                    game = poll_options[str(reaction.emoji)]
                    real_votes[game] = real_votes.get(game, 0) + 1

    if not real_votes:
        chosen_game = "Keine Stimmen abgegeben"
    else:
        sorted_votes = sorted(real_votes.items(), key=lambda kv: kv[1], reverse=True)
        max_votes = sorted_votes[0][1]
        top_options = [option for option, votes in sorted_votes if votes == max_votes]
        chosen_game = top_options[0]  # Falls Gleichstand: einfach erstes nehmen (könnte man randomisieren)

    # Speichern ins Turnier
    tournament = load_tournament_data()
    tournament["poll_results"] = real_votes
    tournament["poll_results"]["chosen_game"] = chosen_game
    tournament["registration_open"] = True
    save_tournament_data(tournament)

    # Poll-Embed posten
    placeholders = {"chosen_game": chosen_game}
    await send_poll_results(channel, placeholders, real_votes)

    # Anmeldung öffnen
    reg_end = tournament.get("registration_end")
    if reg_end:
        formatted_end = reg_end.replace("T", " ")[:16]
    else:
        formatted_end = "Unbekannt"

    await send_registration_open(channel, {"endtime": formatted_end})

    logger.info(f"[POLL] Umfrage beendet. Gewähltes Spiel: {chosen_game}")

    # Reset
    poll_message_id = None
    poll_options = {}

    tournament = load_tournament_data()
    registration_end_str = tournament.get("registration_end")
    if registration_end_str:
        registration_end = datetime.fromisoformat(registration_end_str)
        now = datetime.now(ZoneInfo("UTC"))
        delay_seconds = max(0, int((registration_end - now).total_seconds()))

        add_task("close_registration", asyncio.create_task(close_registration_after_delay(delay_seconds, channel)))
        logger.info(f"[POLL] Anmeldung wird automatisch geschlossen in {delay_seconds // 3600} Stunden.")
    else:
        logger.warning("[POLL] Kein registration_end gefunden – Anmeldung wird NICHT automatisch geschlossen.")

# Event Handler
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    global poll_message_id, poll_votes, poll_options

    if payload.user_id == payload.client.user.id:
        return  # eigene Reaktionen ignorieren

    if payload.message_id != poll_message_id:
        return

    emoji = str(payload.emoji)

    if emoji not in poll_options:
        return  # Keine gültige Option

    # Stimme speichern
    poll_votes[payload.user_id] = emoji

    logger.info(f"[POLL] Stimme registriert: User {payload.user_id} für {emoji}.")
