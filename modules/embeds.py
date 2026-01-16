# modules/embeds.py

import json
import os
import re
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

import discord
from discord import Embed, Interaction, TextChannel

from modules.dataStorage import REMINDER_ENABLED, load_tournament_data
from modules.logger import logger

# Local modules
from modules.config import CONFIG
from modules.utils import smart_send
from modules.reschedule_view import RescheduleView

# Cache for common messages
_common_messages_cache = None


def load_common_messages(language: str = None) -> dict:
    """
    Loads common user-facing messages from locale/{language}/common_messages.json

    These are short messages like permission denials, errors, etc. that don't need full embeds.

    :param language: Language code (default: from CONFIG)
    :return: Dictionary with message categories
    """
    global _common_messages_cache

    if not language:
        language = CONFIG.bot.language

    # Return cached if already loaded
    if _common_messages_cache is not None:
        return _common_messages_cache

    path = os.path.join("locale", language, "common_messages.json")

    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                _common_messages_cache = json.load(f)
                return _common_messages_cache
        except json.JSONDecodeError as e:
            logger.error(f"[MESSAGE LOADER] Error parsing {path}: {e}")
            return {}

    logger.warning(f"[MESSAGE LOADER] common_messages.json not found for language '{language}'.")
    return {}


def get_message(category: str, key: str, **kwargs) -> str:
    """
    Get a localized message from common_messages.json

    :param category: Category like 'PERMISSION', 'ERRORS', 'SUCCESS'
    :param key: Message key within category
    :param kwargs: Optional format parameters
    :return: Formatted message string
    """
    messages = load_common_messages()

    try:
        message = messages.get(category, {}).get(key, f"[Missing: {category}.{key}]")

        # Format with kwargs if provided
        if kwargs:
            message = message.format(**kwargs)

        return message
    except Exception as e:
        logger.error(f"[MESSAGE LOADER] Error getting message {category}.{key}: {e}")
        return f"[Error loading message: {category}.{key}]"


def load_embed_template(template_name: str, language: str = None) -> dict:
    """
    Loads a language-sensitive embed template from:
    locale/{language}/embeds/{template_name}.json

    Fallback on error: locale/default/embeds/{template_name}.json
    """
    if not language:
        language = CONFIG.bot.language

    paths_to_try = [
        os.path.join("locale", language, "embeds", f"{template_name}.json"),
        os.path.join("locale", "default", "embeds", f"{template_name}.json")  # optional fallback
    ]

    for path in paths_to_try:
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                logger.error(f"[EMBED LOADER] Error parsing {path}: {e}")
                return {}

    logger.warning(f"[EMBED LOADER] Template '{template_name}' for language '{language}' not found.")
    return {}


def build_embed_from_template(template: dict, placeholders: dict = None) -> Embed:
    """Builds a Discord Embed from a template dictionary with optional placeholders."""
    if not isinstance(template, dict):
        raise TypeError(f"❌ Embed template must be a dict, but was: {type(template)}")
    # Safely process color
    color_value = template.get("color", 0x3498DB)
    if isinstance(color_value, str):
        color_value = int(color_value.replace("#", "0x"), 16)

    # Get title and description
    title = template.get("title", "No title")
    description = template.get("description", "")

    # Replace placeholders in title and description if provided
    if placeholders:
        for key, value in placeholders.items():
            title = title.replace(f"PLACEHOLDER_{key.upper()}", str(value))
            description = description.replace(f"PLACEHOLDER_{key.upper()}", str(value))

    embed = Embed(
        title=title,
        description=description,
        color=color_value,
    )

    if placeholders:

        # Replace placeholders in fields
        for field in template.get("fields", []):
            name = field.get("name", "")
            value = field.get("value", "")

            for key, val in placeholders.items():
                name = name.replace(f"PLACEHOLDER_{key.upper()}", str(val))
                value = value.replace(f"PLACEHOLDER_{key.upper()}", str(val))

            embed.add_field(name=name, value=value, inline=False)
    else:
        # If no placeholders: add fields normally
        for field in template.get("fields", []):
            embed.add_field(name=field.get("name", ""), value=field.get("value", ""), inline=False)

    # Set footer with placeholder replacement
    if footer := template.get("footer"):
        if placeholders:
            for key, value in placeholders.items():
                footer = footer.replace(f"PLACEHOLDER_{key.upper()}", str(value))
        embed.set_footer(text=footer)

    return embed


# ==== SEND FUNCTIONS ====


async def send_registration_open(channel: TextChannel, placeholders: dict):
    """Sends registration open announcement embed."""
    template = load_embed_template("registration_open").get("REGISTRATION_OPEN_ANNOUNCEMENT")
    if not template:
        logger.error("[EMBED] REGISTRATION_OPEN_ANNOUNCEMENT template missing.")
        return
    embed = build_embed_from_template(template, placeholders)
    await channel.send(embed=embed)


async def send_registration_confirmation(interaction: Interaction, placeholders: dict):
    """
    Sends a confirmation embed after successful registration.
    """
    template_data = load_embed_template("registration")
    template = template_data.get("REGISTRATION_CONFIRMATION")

    if not template:
        logger.error("[EMBED] REGISTRATION_CONFIRMATION template missing.")
        return

    embed = build_embed_from_template(template, placeholders)
    await interaction.response.send_message(embed=embed, ephemeral=False)


async def send_tournament_announcement(channel: TextChannel, placeholders: dict):
    """Sends tournament announcement embed."""
    template = load_embed_template("tournament_start").get("TOURNAMENT_ANNOUNCEMENT")
    if not template:
        logger.error("[EMBED] TOURNAMENT_ANNOUNCEMENT template missing.")
        return
    embed = build_embed_from_template(template, placeholders)
    await channel.send(embed=embed)


async def send_tournament_end_announcement(
    channel: discord.TextChannel,
    mvp_message: str,
    winner_ids: list[str],
    chosen_game: str,
    new_champion_id: Optional[int] = None,
):
    """
    Sends a tournament end embed based on tournament_end.json.

    Args:
        channel: Discord channel to send to
        mvp_message: MVP message string
        winner_ids: List of winner user IDs
        chosen_game: Name of the game that was played
        new_champion_id: Optional ID of new champion

    Note: chosen_game must be passed as parameter because tournament data
    is reset before this function is called.
    """

    template = load_embed_template("tournament_end").get("TOURNAMENT_END")
    if not template:
        logger.error("[EMBED] TOURNAMENT_END template missing.")
        return

    # Process winners
    if winner_ids:
        winners_mentions = ", ".join(f"<@{winner_id}>" for winner_id in winner_ids)
    else:
        winners_mentions = "No winners determined."

    # Prepare champion
    champion_mention = "No champion"  # Default value
    new_champion = channel.guild.get_member(new_champion_id)
    if new_champion:
        champion_mention = new_champion.mention

    # Use standard placeholder format
    placeholders = {
        "mvp_message": mvp_message,
        "winners": winners_mentions,
        "chosen_game": chosen_game,
        "new_champion": champion_mention
    }

    # Build embed with placeholders
    embed = build_embed_from_template(template, placeholders)

    await channel.send(embed=embed)


async def send_tournament_stats(
    interaction: Interaction,
    total_players: int,
    total_wins: int,
    best_player: str,
    favorite_game: str,
):
    """Sends tournament statistics embed."""
    # Placeholders
    placeholders = {
        "total_players": str(total_players),
        "total_wins": str(total_wins),
        "best_player": best_player,
        "favorite_game": favorite_game,
    }

    # Load template
    template = load_embed_template("tournament_stats").get("TOURNAMENT_STATS")
    if not template:
        logger.error("[EMBED] TOURNAMENT_STATS template missing.")
        return

    # Build embed
    embed = build_embed_from_template(template, placeholders)

    # Send response
    await interaction.response.send_message(embed=embed)


async def send_match_reminder(channel: TextChannel, placeholders: dict):
    """Sends match reminder embed."""
    template = load_embed_template("reminder").get("REMINDER")
    if not template:
        logger.error("[EMBED] REMINDER template missing.")
        return

    embed = build_embed_from_template(template, placeholders)

    # Optional player ping
    ping_text = ""

    # 1. Explicit mentions passed?
    if "mentions" in placeholders:
        ping_text = placeholders["mentions"]
        logger.debug("[REMINDER] Mentions taken directly from placeholders.")

    # 2. Fallback via team members (only if REMINDER_ENABLED)
    elif REMINDER_ENABLED:
        tournament = load_tournament_data()
        team1 = placeholders.get("team1")
        team2 = placeholders.get("team2")

        members1 = tournament.get("teams", {}).get(team1, {}).get("members", [])
        members2 = tournament.get("teams", {}).get(team2, {}).get("members", [])

        if not members1 and not members2:
            logger.warning(f"[REMINDER] ⚠️ No members found for teams '{team1}' or '{team2}'.")

        mentions = members1 + members2
        ping_text = " ".join(mentions)
        logger.debug(f"[REMINDER] Mentions automatically generated: {ping_text}")

    # 3. Send
    await channel.send(embed=embed)



async def send_notify_team_members(
    interaction: Interaction,
    team1_members,
    team2_members,
    requesting_team,
    opponent_team,
    new_time,
    match_id: int,
):
    """Sends DM notifications to team members about reschedule request."""
    all_members = team1_members + team2_members
    failed = False

    for member_str in all_members:
        user_id_match = re.search(r"\d+", member_str)
        if not user_id_match:
            continue

        user_id = int(user_id_match.group(0))
        user = interaction.guild.get_member(user_id)

        if user:
            try:
                template = load_embed_template("reschedule").get("RESCHEDULE")
                if not template:
                    logger.error("[EMBED] RESCHEDULE template missing.")
                    continue

                placeholders = {
                    "requesting_team": requesting_team,
                    "opponent_team": opponent_team,
                    "new_time": new_time.strftime("%d.%m.%Y %H:%M"),
                }

                embed = build_embed_from_template(template, placeholders)

                view = RescheduleView(match_id, requesting_team, opponent_team)
                await user.send(embed=embed, view=view)

            except Exception as e:
                logger.warning(f"[RESCHEDULE] Could not send DM to {user.display_name} ({user.id}): {e}")
                failed = True

    return failed


async def send_status(interaction: Interaction, placeholders: dict):
    """
    Sends a status embed based on placeholders.
    """
    template = load_embed_template("status").get("STATUS")
    if not template:
        logger.error("[EMBED] STATUS template missing.")
        return

    embed = build_embed_from_template(template, placeholders)
    await smart_send(interaction, embed=embed)


async def send_match_schedule(interaction: Interaction, description_text: str):
    """Sends match schedule embed with automatic chunking for long text."""
    template = load_embed_template("match_schedule").get("MATCH_SCHEDULE")
    if not template:
        logger.error("[EMBED] MATCH_SCHEDULE template missing.")
        return

    # Check if there are any matches
    if not description_text or description_text.strip() == "":
        embed = build_embed_from_template(template, placeholders=None)
        embed.description = "📭 Noch keine Matches geplant.\n\nMatches werden automatisch erstellt, sobald die Anmeldung geschlossen wird."
        await smart_send(interaction, embed=embed)
        return

    # If text <= 4096 chars it fits directly
    if len(description_text) <= 4096:
        embed = build_embed_from_template(template, placeholders=None)
        embed.description = description_text  # Dynamically override description
        await smart_send(interaction, embed=embed)
    else:
        # Split text into 4096-char chunks
        chunks = [description_text[i : i + 4096] for i in range(0, len(description_text), 4096)]

        for idx, chunk in enumerate(chunks):
            embed = build_embed_from_template(template, placeholders=None)
            embed.description = chunk  # Always new embed object based on template

            if idx == 0:
                await smart_send(interaction, embed=embed)  # first time (e.g. ephemeral etc.)
            else:
                await interaction.channel.send(embed=embed)  # then just in channel


async def send_match_schedule_for_channel(channel: discord.TextChannel, description_text: str):
    """Sends match schedule embed to channel with automatic chunking."""
    template = load_embed_template("match_schedule").get("MATCH_SCHEDULE")
    if not template:
        logger.error("[EMBED] MATCH_SCHEDULE template missing.")
        return

    # Check if there are any matches
    if not description_text or description_text.strip() == "":
        embed = build_embed_from_template(template, placeholders=None)
        embed.description = "📭 Noch keine Matches geplant.\n\nMatches werden automatisch erstellt, sobald die Anmeldung geschlossen wird."
        await channel.send(embed=embed)
        return

    # If text <= 4096 chars it fits directly
    if len(description_text) <= 4096:
        embed = build_embed_from_template(template, placeholders=None)
        embed.description = description_text  # Dynamically override description
        await channel.send(embed=embed)
    else:
        # Split text into 4096-char chunks
        chunks = [description_text[i : i + 4096] for i in range(0, len(description_text), 4096)]

        for chunk in chunks:
            embed = build_embed_from_template(template, placeholders=None)
            embed.description = chunk
            await channel.send(embed=embed)


# Removed: send_poll_results() - now combined with send_registration_open()
# Removed: send_help() - now uses /info help command


async def send_global_stats(interaction: Interaction, description_text: str):
    """Sends global statistics embed."""
    template = load_embed_template("global_stats").get("GLOBAL_STATS")
    if not template:
        logger.error("[EMBED] GLOBAL_STATS template missing.")
        return
    embed = build_embed_from_template(template, placeholders=None)
    embed.description = description_text
    await smart_send(interaction, embed=embed)


async def send_list_matches(interaction: Interaction, matches: list):
    """Sends a list of matches embed with automatic pagination."""

    template_data = load_embed_template("list_matches")
    template = template_data.get("LIST_MATCHES")

    if not template:
        logger.error("[EMBED] LIST_MATCHES template missing.")
        return

    if not matches:
        await smart_send(interaction, content="⚠️ No matches scheduled.", ephemeral=True)
        return

    placeholders = {}
    embeds = []
    count = 0

    embed = build_embed_from_template(template, placeholders)

    for match in matches:
        team1 = match.get("team1", "Unknown")
        team2 = match.get("team2", "Unknown")
        scheduled_time = match.get("scheduled_time")

        if scheduled_time:
            try:
                dt = datetime.fromisoformat(scheduled_time)
                # If no timezone set, interpret as UTC:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=ZoneInfo("UTC"))
                # Convert to Europe/Berlin:
                dt_berlin = dt.astimezone(ZoneInfo("Europe/Berlin"))
                scheduled_time_str = dt_berlin.strftime("%d.%m.%Y %H:%M")
            except Exception:
                scheduled_time_str = "❗ Invalid time"
        else:
            scheduled_time_str = "⏳ Not yet scheduled"

        status = match.get("status", "open").capitalize()

        embed.add_field(
            name=f"{team1} vs {team2}",
            value=f"🕒 Scheduled: {scheduled_time}\n📋 Status: {status}",
            inline=False,
        )
        count += 1

        if count == 25:
            embeds.append(embed)
            embed = build_embed_from_template(template, placeholders)
            count = 0

    if count > 0:
        embeds.append(embed)

    # First response
    await interaction.response.send_message(embed=embeds[0], ephemeral=True)

    # Additional embeds (if more than one)
    for embed in embeds[1:]:
        await interaction.followup.send(embed=embed, ephemeral=True)


# Removed: send_cleanup_summary() - now uses logging only to reduce channel spam


async def send_participants_overview(interaction: Interaction, participants_text: str):
    """
    Sends an overview of all participants as an embed.
    """
    template = load_embed_template("participants").get("PARTICIPANTS_OVERVIEW")

    if not template:
        logger.error("[EMBED] PARTICIPANTS_OVERVIEW template missing.")
        return

    placeholders = {"PARTICIPANTS": participants_text}

    embed = build_embed_from_template(template, placeholders)
    await interaction.response.send_message(embed=embed, ephemeral=False)


async def send_request_reschedule(
    destination: discord.TextChannel,
    match_id: int,
    team1: str,
    team2: str,
    new_datetime: datetime,
    valid_members: List[discord.Member],
):
    """
    Sends a reschedule embed to the reschedule channel with buttons for affected players.
    """
    mentions = " ".join(m.mention for m in valid_members)

    embed = discord.Embed(
        title="🕐 Match Rescheduling Request",
        description=(
            f"**Match:** {team1} vs {team2}\n"
            f"**New date:** {new_datetime.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"{mentions}\n\n"
            "Please vote: ✅ Accept or ❌ Decline.\n"
            "*Deadline: 24h from now*"
        ),
        color=0x3498DB,
    )

    view = RescheduleView(match_id, team1, team2, new_datetime, valid_members)

    sent_message = await destination.send(embed=embed, view=view)
    view.message = sent_message


async def send_wrong_channel(interaction: Interaction):
    """Sends wrong channel warning embed."""
    template = load_embed_template("wrong_channel").get("WRONG_CHANNEL")
    if not template:
        logger.error("[EMBED] WRONG_CHANNEL template missing.")
        return
    embed = build_embed_from_template(template)
    await interaction.response.send_message(embed=embed, ephemeral=False)


async def send_registration_closed(channel: discord.TextChannel):
    """Sends registration closed announcement embed."""
    template = load_embed_template("close").get("REGISTRATION_CLOSED_ANNOUNCEMENT")
    if not template:
        logger.error("[EMBED] REGISTRATION_CLOSED_ANNOUNCEMENT template missing.")
        return

    embed = build_embed_from_template(template)
    await channel.send(embed=embed)
