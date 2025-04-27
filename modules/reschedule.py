from discord import app_commands, Interaction, ButtonStyle, Embed
from discord.ext import commands
from discord.ui import View, Button
import discord
from datetime import datetime, timedelta
import logging
import re

# Lokale modules
from modules.dataStorage import load_tournament_data, save_tournament_data, load_config
from modules.utils import smart_send, get_player_team, get_team_open_matches
from modules.matchmaker import generate_weekend_slots
from modules.embeds import send_notify_team_members, send_request_reschedule, build_embed_from_template
from modules.logger import logger
from views.reschedule_view import RescheduleView
from modules.shared_states import pending_reschedules

config = load_config()
RESCHEDULE_CHANNEL_ID = int(config.get("CHANNELS", {}).get("RESCHEDULE_CHANNEL_ID", 0))


# ---------------------------------------
# Helper: IDs extrahieren
# ---------------------------------------

def extract_ids(members):
    ids = []
    for m in members:
        match = re.search(r"\d+", m)
        if match:
            ids.append(match.group(0))
    return ids

# ---------------------------------------
# Command: /request_reschedule
# ---------------------------------------

@app_commands.command(name="request_reschedule", description="Fordere eine Neuansetzung für ein Match an.")
async def request_reschedule(interaction: Interaction, match_id: int, neuer_zeitpunkt: str):
    global pending_reschedules
    tournament = load_tournament_data()
    user_id = str(interaction.user.id)

    # ➔ Prüfen: Gibt es schon eine aktive Anfrage für dieses Match?
    if match_id in pending_reschedules:
        await interaction.response.send_message("🚫 Für dieses Match läuft bereits eine Reschedule-Anfrage!", ephemeral=True)
        return

    # ➔ Wenn alles gut, Match-ID als "offen" markieren
    pending_reschedules.add(match_id)

    team_name = get_player_team(user_id)
    if not team_name:
        await interaction.response.send_message("🚫 Du bist in keinem Team registriert.", ephemeral=True)
        return

    open_matches = get_team_open_matches(team_name)
    if match_id not in [m["match_id"] for m in open_matches]:
        await interaction.response.send_message("🚫 Du kannst nur deine eigenen Matches verschieben.", ephemeral=True)
        return

    match = next((m for m in tournament.get("matches", []) if m.get("match_id") == match_id), None)
    if not match:
        await interaction.response.send_message("🚫 Match nicht gefunden.", ephemeral=True)
        return

    # ➔ Check: Steht der Matchbeginn kurz bevor?
    scheduled_time_str = match.get("scheduled_time")
    if scheduled_time_str:
        scheduled_dt = datetime.strptime(scheduled_time_str, "%Y-%m-%dT%H:%M:%S")
        now = datetime.utcnow()

    if scheduled_dt - now <= timedelta(hours=1):
        await interaction.response.send_message("🚫 Du kannst Matches nur bis spätestens 1 Stunde vor Beginn verschieben.", ephemeral=True)
        return

    try:
        parsed_datetime = datetime.strptime(neuer_zeitpunkt, "%d.%m.%Y %H:%M")
    except ValueError:
        await interaction.response.send_message("🚫 Ungültiges Format! Nutze TT.MM.JJJJ HH:MM.", ephemeral=True)
        return

    team1 = match["team1"]
    team2 = match["team2"]
    members_team1 = tournament.get("teams", {}).get(team1, {}).get("members", [])
    members_team2 = tournament.get("teams", {}).get(team2, {}).get("members", [])
    all_mentions = members_team1 + members_team2

    valid_members = []
    for mention in all_mentions:
        if mention.startswith("<@"):
            try:
                user_id = int(mention.replace("<@", "").replace("!", "").replace(">", ""))
                member = interaction.guild.get_member(user_id)
                if member:
                    valid_members.append(member)
            except ValueError:
                continue

    # ➔ Channel Backup
    reschedule_channel = interaction.guild.get_channel(RESCHEDULE_CHANNEL_ID)
    if not reschedule_channel:
        await interaction.response.send_message("🚫 Reschedule-Channel nicht gefunden.", ephemeral=True)
        return

    # ➔ DM versuchen
    for member in valid_members:
        try:
            if not reschedule_channel.permissions_for(interaction.guild.me).send_messages:
                await interaction.response.send_message("🚫 Ich habe keine Berechtigung, in den Reschedule-Channel zu schreiben!", ephemeral=True)
                logger.warning("[RESCHEDULE] Fehlende Schreibrechte im Reschedule-Channel.")
                return
            await send_request_reschedule(member, match_id, team1, team2, parsed_datetime, [m.mention for m in valid_members])
            logger.info(f"[RESCHEDULE] DM an {member.display_name} erfolgreich gesendet.")
        except discord.Forbidden:
            logger.warning(f"[RESCHEDULE] DM an {member.display_name} fehlgeschlagen. Sende stattdessen in den Reschedule-Channel.")
        except Exception as e:
            logger.error(f"[RESCHEDULE] Unerwarteter Fehler beim DM-Versand an {member.display_name}: {e}")


    await send_request_reschedule(reschedule_channel, match_id, team1, team2, parsed_datetime, [m.mention for m in valid_members])

    await interaction.response.send_message("✅ Deine Reschedule-Anfrage wurde erstellt!", ephemeral=True)
    logger.info(f"[RESCHEDULE] Anfrage von {team_name} für Match {match_id} erstellt.")







# ---------------------------------------
# Autocomplete für Match-ID
# ---------------------------------------

@request_reschedule.autocomplete("match_id")
async def match_id_autocomplete(interaction: Interaction, current: str):
    tournament = load_tournament_data()
    user_id = str(interaction.user.id)
    team_name = get_player_team(user_id)

    if not team_name:
        return []

    open_matches = get_team_open_matches(team_name)

    choices = []
    for m in open_matches:
        if current in str(m["match_id"]):
            choices.append(
                app_commands.Choice(
                    name=f"Match {m['match_id']}: {m['team1']} vs {m['team2']}",
                    value=m["match_id"]
                )
            )
    return choices[:25]  # Discord erlaubt maximal 25 Vorschläge

# ---------------------------------------
# Helper: Autocomplete für neue Terminwahl
# ---------------------------------------

@request_reschedule.autocomplete("neuer_zeitpunkt")
async def neuer_zeitpunkt_autocomplete(interaction: Interaction, current: str):
    tournament = load_tournament_data()

    try:
        all_slots = generate_weekend_slots(tournament)
    except ValueError:
        # Falls noch keine Matches existieren ➔ einfach KEINE Vorschläge machen
        return []

    # Schon belegte Slots raussuchen
    booked_slots = set()
    for match in tournament.get("matches", []):
        if match.get("scheduled_time"):
            booked_slots.add(match["scheduled_time"])

    # Freie Slots herausfiltern
    free_slots = [slot for slot in all_slots if slot not in booked_slots]

    if current:
        free_slots = [slot for slot in free_slots if current in slot]

    choices = []
    for slot in free_slots[:25]:
        dt = datetime.fromisoformat(slot)
        label = f"{dt.strftime('%A')} {dt.strftime('%d.%m.%Y %H:%M')} Uhr"
        value = dt.strftime('%d.%m.%Y %H:%M')
        choices.append(app_commands.Choice(name=label, value=value))

    return choices

