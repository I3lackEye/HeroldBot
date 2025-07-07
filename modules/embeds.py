# modules/embeds.py

import json
import os
import re
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

import discord
from discord import Embed, Interaction, TextChannel



# Lokale Module
from modules.utils import load_config, smart_send
from views.reschedule_view import RescheduleView
from modules.dataStorage import load_tournament_data
from modules.logger import logger
from modules.dataStorage import REMINDER_PING


def load_embed_template(template_name: str, category: str = "default") -> dict:
    """
    Lädt ein Embed-Template aus configs/embeds/{category}/{template_name}.json
    """
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "configs", "embeds", category))
    embed_path = os.path.join(base_dir, f"{template_name}.json")

    try:
        with open(embed_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"[EMBED LOADER] Template '{template_name}' in Kategorie '{category}' nicht gefunden.")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"[EMBED LOADER] Fehler beim Parsen von {embed_path}: {e}")
        return {}


def build_embed_from_template(template: dict, placeholders: dict = None) -> Embed:
    # Farbe sicher verarbeiten
    color_value = template.get("color", 0x3498DB)
    if isinstance(color_value, str):
        color_value = int(color_value.replace("#", "0x"), 16)

    embed = Embed(
        title=template.get("title", "Kein Titel"),
        description=template.get("description", ""),
        color=color_value,
    )

    if placeholders:
        # Beschreibung Platzhalter ersetzen
        for key, value in placeholders.items():
            embed.description = embed.description.replace(f"PLACEHOLDER_{key.upper()}", str(value))

        # Felder Platzhalter ersetzen
        for field in template.get("fields", []):
            name = field.get("name", "")
            value = field.get("value", "")

            for key, val in placeholders.items():
                name = name.replace(f"PLACEHOLDER_{key.upper()}", str(val))
                value = value.replace(f"PLACEHOLDER_{key.upper()}", str(val))

            embed.add_field(name=name, value=value, inline=False)
    else:
        # Falls keine Platzhalter: Felder normal hinzufügen
        for field in template.get("fields", []):
            embed.add_field(name=field.get("name", ""), value=field.get("value", ""), inline=False)

    if footer := template.get("footer"):
        embed.set_footer(text=footer)

    return embed


# ==== SEND FUNKTIONEN ====


async def send_registration_open(channel: TextChannel, placeholders: dict):
    template = load_embed_template("registration_open", category="default").get("REGISTRATION_OPEN_ANNOUNCEMENT")
    if not template:
        logger.error("[EMBED] REGISTRATION_OPEN_ANNOUNCEMENT Template fehlt.")
        return
    embed = build_embed_from_template(template, placeholders)
    await channel.send(embed=embed)


async def send_registration_confirmation(interaction: Interaction, placeholders: dict):
    """
    Sendet ein Bestätigungs-Embed nach erfolgreicher Anmeldung.
    """
    template_data = load_embed_template("registration", category="default")
    template = template_data.get("REGISTRATION_CONFIRMATION")

    if not template:
        logger.error("[EMBED] REGISTRATION_CONFIRMATION Template fehlt.")
        return

    embed = build_embed_from_template(template, placeholders)
    await interaction.response.send_message(embed=embed, ephemeral=False)


async def send_tournament_announcement(channel: TextChannel, placeholders: dict):
    template = load_embed_template("tournament_start", category="default").get("TOURNAMENT_ANNOUNCEMENT")
    if not template:
        logger.error("[EMBED] TOURNAMENT_ANNOUNCEMENT Template fehlt.")
        return
    embed = build_embed_from_template(template, placeholders)
    await channel.send(embed=embed)


async def send_tournament_end_announcement(
    channel: discord.TextChannel,
    mvp_message: str,
    winner_ids: list[str],
    new_champion_id: Optional[int] = None,
):
    """
    Sendet ein Abschluss-Embed für das Turnier basierend auf tournament_end.json.
    """

    template = load_embed_template("tournament_end", category="default").get("TOURNAMENT_END")
    if not template:
        logger.error("[EMBED] TOURNAMENT_END Template fehlt.")
        return

    tournament = load_tournament_data()
    if tournament is None:
        logger.error("[TOURNAMENT] Kein aktives Turnier gefunden beim Senden des Abschluss-Embeds!")
        await channel.send("❌ Fehler: Es konnte kein Turnier gefunden werden, um den Abschluss-Embed zu senden.")
        return

    poll_results = tournament.get("poll_results") or {}
    chosen_game = poll_results.get("chosen_game", "Unbekannt")

    # Gewinner verarbeiten
    if winner_ids:
        winners_mentions = ", ".join(f"<@{winner_id}>" for winner_id in winner_ids)
    else:
        winners_mentions = "Keine Gewinner ermittelt."

    # Champion vorbereiten
    champion_mention = "Kein Champion"  # Standardwert
    new_champion = channel.guild.get_member(new_champion_id)
    if new_champion:
        champion_mention = new_champion.mention

    # Jetzt den Text richtig ersetzen
    description_text = template.get("description", "")
    description_text = description_text.replace("{MVP_MESSAGE}", mvp_message)
    description_text = description_text.replace("{WINNERS}", winners_mentions)
    description_text = description_text.replace("{CHOSEN_GAME}", chosen_game)
    description_text = description_text.replace("{NEW_CHAMPION}", champion_mention)

    # Jetzt Embed bauen
    embed = build_embed_from_template(template, placeholders=None)
    embed.description = description_text

    await channel.send(embed=embed)


async def send_tournament_stats(
    interaction: Interaction,
    total_players: int,
    total_wins: int,
    best_player: str,
    favorite_game: str,
):
    # Platzhalter
    placeholders = {
        "total_players": str(total_players),
        "total_wins": str(total_wins),
        "best_player": best_player,
        "favorite_game": favorite_game,
    }

    # Template laden
    template = load_embed_template("tournament_stats", category="default").get("TOURNAMENT_STATS")
    if not template:
        logger.error("[EMBED] TOURNAMENT_STATS Template fehlt.")
        return

    # Embed bauen
    embed = build_embed_from_template(template, placeholders)

    # Antwort senden
    await interaction.response.send_message(embed=embed)


async def send_match_reminder(channel: TextChannel, placeholders: dict):
    template = load_embed_template("reminder", category="default").get("REMINDER")
    if not template:
        logger.error("[EMBED] REMINDER Template fehlt.")
        return

    embed = build_embed_from_template(template, placeholders)

    # Optional ping der Spieler
    ping_text = ""
    if REMINDER_PING:
        tournament = load_tournament_data()
        team1 = placeholders.get("team1")
        team2 = placeholders.get("team2")
        members1 = tournament.get("teams", {}).get(team1, {}).get("members", [])
        members2 = tournament.get("teams", {}).get(team2, {}).get("members", [])
        mentions = members1 + members2
        ping_text = " ".join(mentions)

    await channel.send(content=ping_text if ping_text else None, embed=embed)


async def send_notify_team_members(
    interaction: Interaction,
    team1_members,
    team2_members,
    requesting_team,
    opponent_team,
    neuer_zeitpunkt,
    match_id: int,
):
    all_members = team1_members + team2_members
    failed = False

    for member_str in all_members:
        user_id_match = re.search(r"\\d+", member_str)
        if not user_id_match:
            continue

        user_id = int(user_id_match.group(0))
        user = interaction.guild.get_member(user_id)

        if user:
            try:
                template = load_embed_template("reschedule", category="default").get("RESCHEDULE")
                if not template:
                    logger.error("[EMBED] RESCHEDULE Template fehlt.")
                    continue

                placeholders = {
                    "requesting_team": requesting_team,
                    "opponent_team": opponent_team,
                    "new_time": neuer_zeitpunkt.strftime("%d.%m.%Y %H:%M"),
                }

                embed = build_embed_from_template(template, placeholders)

                view = RescheduleView(match_id, requesting_team, opponent_team)
                await user.send(embed=embed, view=view)

            except Exception as e:
                logger.warning(f"[RESCHEDULE] Konnte DM an {user.display_name} ({user.id}) nicht senden: {e}")
                failed = True

    return failed


async def send_status(interaction: Interaction, placeholders: dict):
    """
    Sendet ein Status-Embed basierend auf den Platzhaltern.
    """
    template = load_embed_template("status", category="default").get("STATUS")
    if not template:
        logger.error("[EMBED] STATUS Template fehlt.")
        return

    embed = build_embed_from_template(template, placeholders)
    await smart_send(interaction, embed=embed)


async def send_match_schedule(interaction: Interaction, description_text: str):
    template = load_embed_template("match_schedule", category="default").get("MATCH_SCHEDULE")
    if not template:
        logger.error("[EMBED] MATCH_SCHEDULE Template fehlt.")
        return

    # Wenn Text <= 4096 Zeichen passt er direkt rein
    if len(description_text) <= 4096:
        embed = build_embed_from_template(template, placeholders=None)
        embed.description = description_text  # Beschreibung dynamisch überschreiben
        await smart_send(interaction, embed=embed)
    else:
        # Text aufteilen in 4096er-Blöcke
        chunks = [description_text[i : i + 4096] for i in range(0, len(description_text), 4096)]

        for idx, chunk in enumerate(chunks):
            embed = build_embed_from_template(template, placeholders=None)
            embed.description = chunk  # Immer neues Embed-Objekt auf Basis des Templates

            if idx == 0:
                await smart_send(interaction, embed=embed)  # erstes Mal (z.B. ephemeral etc.)
            else:
                await interaction.channel.send(embed=embed)  # danach einfach in den Channel


async def send_match_schedule_for_channel(channel: discord.TextChannel, description_text: str):
    template = load_embed_template("match_schedule", category="default").get("MATCH_SCHEDULE")
    if not template:
        logger.error("[EMBED] MATCH_SCHEDULE Template fehlt.")
        return

    # Wenn Text <= 4096 Zeichen passt er direkt rein
    if len(description_text) <= 4096:
        embed = build_embed_from_template(template, placeholders=None)
        embed.description = description_text  # Beschreibung dynamisch überschreiben
        await channel.send(embed=embed)
    else:
        # Text aufteilen in 4096er-Blöcke
        chunks = [description_text[i : i + 4096] for i in range(0, len(description_text), 4096)]

        for chunk in chunks:
            embed = build_embed_from_template(template, placeholders=None)
            embed.description = chunk
            await channel.send(embed=embed)


async def send_poll_results(channel: TextChannel, placeholders: dict, poll_results: dict):
    template = load_embed_template("poll", category="default").get("POLL_RESULT")
    if not template:
        logger.error("[EMBED] POLL_RESULT Template fehlt.")
        return

    embed = build_embed_from_template(template, placeholders)

    # Nur echte Spiele filtern (ohne "chosen_game")
    real_votes = {k: v for k, v in poll_results.items() if k != "chosen_game"}

    sorted_games = sorted(real_votes.items(), key=lambda kv: kv[1], reverse=True)

    for game, votes in sorted_games:
        embed.add_field(name=game, value=f"**{votes} Stimmen**", inline=False)

    if "chosen_game" in poll_results:
        embed.add_field(name="🏆 Gewonnen", value=f"**{poll_results['chosen_game']}**", inline=False)

    await channel.send(embed=embed)


async def send_help(interaction: Interaction):
    template = load_embed_template("help", category="default").get("HELP")
    if not template:
        logger.error("[EMBED] HELP Template fehlt.")
        return

    embed = build_embed_from_template(template, placeholders=None)

    await interaction.response.send_message(embed=embed, ephemeral=True)


async def send_global_stats(interaction: Interaction, description_text: str):
    template = load_embed_template("global_stats", category="default").get("GLOBAL_STATS")
    if not template:
        logger.error("[EMBED] GLOBAL_STATS Template fehlt.")
        return
    embed = build_embed_from_template(template, placeholders)
    await channel.send(embed=embed)


async def send_list_matches(interaction: Interaction, matches: list):

    template_data = load_embed_template("list_matches", category="default")
    template = template_data.get("LIST_MATCHES")

    if not template:
        logger.error("[EMBED] LIST_MATCHES Template fehlt.")
        return

    if not matches:
        await smart_send(interaction, content="⚠️ Keine Matches geplant.", ephemeral=True)
        return

    placeholders = {}
    embeds = []
    count = 0

    embed = build_embed_from_template(template, placeholders)

    for match in matches:
        team1 = match.get("team1", "Unbekannt")
        team2 = match.get("team2", "Unbekannt")
        scheduled_time = match.get("scheduled_time")

        if scheduled_time:
            try:
                dt = datetime.fromisoformat(scheduled_time)
                # Wenn keine Zeitzone gesetzt, als UTC interpretieren:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=ZoneInfo("UTC"))
                # Nach Europe/Berlin umwandeln:
                dt_berlin = dt.astimezone(ZoneInfo("Europe/Berlin"))
                scheduled_time_str = dt_berlin.strftime("%d.%m.%Y %H:%M")
            except Exception:
                scheduled_time_str = "❗ Ungültige Zeit"
        else:
            scheduled_time_str = "⏳ Noch nicht geplant"

        status = match.get("status", "offen").capitalize()

        embed.add_field(
            name=f"{team1} vs {team2}",
            value=f"🕒 Geplant: {scheduled_time}\n📋 Status: {status}",
            inline=False,
        )
        count += 1

        if count == 25:
            embeds.append(embed)
            embed = build_embed_from_template(template, placeholders)
            count = 0

    if count > 0:
        embeds.append(embed)

    # Erste Antwort
    await interaction.response.send_message(embed=embeds[0], ephemeral=True)

    # Weitere Embeds (falls mehr als einer)
    for embed in embeds[1:]:
        await interaction.followup.send(embed=embed, ephemeral=True)


async def send_cleanup_summary(channel: discord.TextChannel, teams_deleted: list, players_rescued: list):
    template = load_embed_template("cleanup", category="default").get("CLEANUP_SUMMARY")
    if not template:
        logger.error("[EMBED] CLEANUP_SUMMARY Template fehlt.")
        return

    # Embed bauen
    embed = build_embed_from_template(template)

    desc_parts = []

    if teams_deleted:
        teams_text = "\n".join(f"• {team}" for team in teams_deleted)
        desc_parts.append(f"**🗑️ Gelöschte Teams:**\n{teams_text}")

    if players_rescued:
        players_text = "\n".join(f"• {player}" for player in players_rescued)
        desc_parts.append(f"**👤 Gerettete Spieler:**\n{players_text}")

    if desc_parts:
        embed.description = "\n\n".join(desc_parts)
    else:
        embed.description = "Keine unvollständigen Teams gefunden."

    await channel.send(embed=embed)


async def send_participants_overview(interaction: Interaction, participants_text: str):
    """
    Sendet eine Übersicht aller Teilnehmer als Embed.
    """
    template = load_embed_template("participants", category="default").get("PARTICIPANTS_OVERVIEW")

    if not template:
        logger.error("[EMBED] PARTICIPANTS_OVERVIEW Template fehlt.")
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
    Sendet ein Reschedule-Embed in den Reschedule-Channel mit Buttons für die betroffenen Spieler.
    """
    mentions = " ".join(m.mention for m in valid_members)

    embed = discord.Embed(
        title="🕐 Anfrage zur Matchverschiebung",
        description=(
            f"**Match:** {team1} vs {team2}\n"
            f"**Neuer Termin:** {new_datetime.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"{mentions}\n\n"
            "Bitte stimmt ab: ✅ Akzeptieren oder ❌ Ablehnen.\n"
            "*Deadline: 24h ab jetzt*"
        ),
        color=0x3498DB,
    )

    view = RescheduleView(match_id, team1, team2, new_datetime, valid_members)

    sent_message = await destination.send(embed=embed, view=view)
    view.message = sent_message


async def send_wrong_channel(interaction: Interaction):
    template = load_embed_template("wrong_channel", category="default").get("WRONG_CHANNEL")
    if not template:
        logger.error("[EMBED] WRONG_CHANNEL Template fehlt.")
        return
    embed = build_embed_from_template(template)
    await interaction.response.send_message(embed=embed, ephemeral=False)


async def send_registration_closed(channel: discord.TextChannel):
    template = load_embed_template("close", category="default").get("REGISTRATION_CLOSED_ANNOUNCEMENT")
    if not template:
        logger.error("[EMBED] REGISTRATION_CLOSED_ANNOUNCEMENT Template fehlt.")
        return

    embed = build_embed_from_template(template)
    await channel.send(embed=embed)
