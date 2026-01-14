# modules/poll.py
import asyncio
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from modules.embeds import get_message
import discord
from discord.ext import commands

# Local modules
from modules.config import CONFIG
from modules.dataStorage import load_tournament_data, save_tournament_data, load_games
from modules.embeds import send_registration_open
from modules.logger import logger
from modules.task_manager import add_task
from modules.tournament import auto_end_poll, close_registration_after_delay

# Global variables
poll_message_id = None
poll_channel_id = None
poll_votes = {}  # user_id -> emoji
poll_options = {}  # emoji -> game_name
_poll_lock = asyncio.Lock()  # Prevent race conditions

emoji_list = ["🇦", "🇧", "🇨", "🇩", "🇪", "🇫", "🇬", "🇭", "🇮", "🇯"]


async def start_poll(
    channel: discord.TextChannel,
    options: list[str],
    registration_hours: int = 72,
    poll_duration_hours: int = 48,
):
    """
    Starts a game voting poll with the given options.

    :param channel: Discord channel to send the poll to
    :param options: List of game options
    :param registration_hours: Hours until registration closes
    :param poll_duration_hours: Hours until poll ends
    """
    global poll_message_id, poll_channel_id, poll_votes, poll_options

    description = ""
    temp_poll_options = {}

    for idx, (game_id, game_data) in enumerate(options.items()):
        if idx >= len(emoji_list):
            break  # Use maximum available emojis
        emoji = emoji_list[idx]
        game_name = game_data.get("name", game_id)  # Fallback: Key if no name exists
        description += f"{emoji} {game_name}\n"
        temp_poll_options[emoji] = game_id  # Important: Keep ID as reference

    # Calculate end time
    poll_end_time = datetime.now(tz=ZoneInfo(CONFIG.bot.timezone)) + timedelta(hours=registration_hours)
    poll_end_str = poll_end_time.strftime("%d.%m.%Y %H:%M")

    embed = discord.Embed(
        title="🎮 Vote: Which game should we play?",
        description=description,
        color=discord.Color.blue(),
    )

    embed.set_footer(text=f"⏳ Poll ends on: {poll_end_str}")

    message = await channel.send(embed=embed)

    for emoji in temp_poll_options.keys():
        await message.add_reaction(emoji)

    async with _poll_lock:
        poll_message_id = message.id
        poll_channel_id = message.channel.id
        poll_votes = {}
        poll_options = temp_poll_options
        logger.info(f"[POLL] New poll started with {len(options)} options.")


async def end_poll(bot: discord.Client, channel: discord.TextChannel):
    """
    Ends the current poll and determines the winning game.
    If no votes were cast, a random game is selected.
    """
    global poll_message_id, poll_options

    # Check if poll exists (thread-safe)
    async with _poll_lock:
        current_poll_id = poll_message_id
        current_options = dict(poll_options)

    if not current_poll_id:
        await channel.send(get_message("ERRORS", "no_active_poll"))
        return

    try:
        message = await channel.fetch_message(current_poll_id)
    except Exception as e:
        logger.error(f"[POLL] Error fetching poll message: {e}")
        await channel.send(get_message("ERRORS", "poll_fetch_error"))
        return

    real_votes = {}

    for reaction in message.reactions:
        if str(reaction.emoji) in current_options:
            async for user in reaction.users():
                if not user.bot:
                    game = current_options[str(reaction.emoji)]
                    real_votes[game] = real_votes.get(game, 0) + 1

    # Load games for name conversion
    all_games = load_games()

    if not real_votes:
        visible_games = [
            g["name"] for g in all_games.values() if g.get("visible_in_poll", True)
        ]

        if visible_games:
            chosen_game_name = random.choice(visible_games)
            logger.warning(f"[POLL] ⚠️ No votes cast – randomly chosen: {chosen_game_name}")
        else:
            chosen_game_name = "No games available"
            logger.error("[POLL] ❌ No games available – poll empty")
    else:
        sorted_votes = sorted(real_votes.items(), key=lambda kv: kv[1], reverse=True)
        max_votes = sorted_votes[0][1]
        top_options = [option for option, votes in sorted_votes if votes == max_votes]
        chosen_game_id = top_options[0]  # This is the game ID (e.g., "Gates_of_Hell")

        # Convert game ID to display name
        chosen_game_name = all_games.get(chosen_game_id, {}).get("name", chosen_game_id)


    # Save to tournament
    tournament = load_tournament_data()
    # Update poll_results without completely overwriting (preserves pre-set values in tests)
    if "poll_results" not in tournament:
        tournament["poll_results"] = {}
    tournament["poll_results"].update(real_votes)
    tournament["poll_results"]["chosen_game"] = chosen_game_name
    tournament["registration_open"] = True
    save_tournament_data(tournament)

    # Open registration with poll results combined
    reg_end = tournament.get("registration_end")
    if reg_end:
        formatted_end = reg_end.replace("T", " ")[:16]
    else:
        formatted_end = "Unknown"

    # Format votes for display - convert game IDs to display names
    if real_votes:
        vote_items = []
        for game_id, votes in sorted(real_votes.items(), key=lambda x: x[1], reverse=True):
            game_name = all_games.get(game_id, {}).get("name", game_id)
            vote_items.append(f"{game_name}: {votes}")
        vote_text = ", ".join(vote_items)
    else:
        vote_text = "Keine Stimmen abgegeben (zufällig gewählt)"

    placeholders = {
        "game": chosen_game_name,
        "votes": vote_text,
        "endtime": formatted_end
    }

    await send_registration_open(channel, placeholders)

    logger.info(f"[POLL] Poll ended. Chosen game: {chosen_game_name}")

    # Reset (thread-safe)
    async with _poll_lock:
        poll_message_id = None
        poll_options = {}

    tournament = load_tournament_data()
    registration_end_str = tournament.get("registration_end")
    if registration_end_str:
        # Get timezone from config
        tz = ZoneInfo(CONFIG.bot.timezone)

        registration_end = datetime.fromisoformat(registration_end_str)

        # If no timezone: use configured timezone
        if registration_end.tzinfo is None:
            registration_end = registration_end.replace(tzinfo=tz)

        now = datetime.now(tz=tz)
        logger.debug(f"registration_end: {registration_end} ({registration_end.tzinfo})")
        logger.debug(f"now: {now} ({now.tzinfo})")
        delay_seconds = max(0, int((registration_end - now).total_seconds()))

        add_task(
            "close_registration",
            asyncio.create_task(close_registration_after_delay(delay_seconds, channel)),
        )
        logger.info(f"[POLL] Registration will auto-close in {delay_seconds // 3600} hours.")
    else:
        logger.warning("[POLL] No registration_end found – registration will NOT auto-close.")


# Event Handler
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """
    Handles reaction adds to poll messages.
    Registers votes for valid poll options.
    """
    global poll_message_id, poll_votes, poll_options

    if payload.user_id == payload.client.user.id:
        return  # ignore own reactions

    if payload.message_id != poll_message_id:
        return

    emoji = str(payload.emoji)

    async with _poll_lock:
        if emoji not in poll_options:
            return  # Not a valid option

        # Save vote
        poll_votes[payload.user_id] = emoji

        logger.info(f"[POLL] Vote registered: User {payload.user_id} for {emoji}.")
