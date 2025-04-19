from discord import app_commands, Interaction, ButtonStyle
from discord.ui import View, Button
from datetime import datetime
import logging
import re

from .dataStorage import load_tournament_data, save_tournament_data, load_config
from .utils import smart_send, get_player_team, get_team_open_matches, generate_weekend_slots
from .embeds import create_embed_from_config

logger = logging.getLogger("discord")

config = load_config()
RESCHEDULE_CHANNEL_ID = int(config.get("CHANNELS", {}).get("RESCHEDULE_CHANNEL_ID", 0))

# ---------------------------------------
# View für Reschedule Buttons
# ---------------------------------------

class RescheduleView(View):
    def __init__(self, match_id: int, requesting_team: str, opponent_team: str):
        super().__init__(timeout=86400)
        self.match_id = match_id
        self.requesting_team = requesting_team
        self.opponent_team = opponent_team
        self.accepted_by = set()

        self.accept_button = Button(label="✅ Akzeptieren", style=ButtonStyle.success)
        self.accept_button.callback = self.accept_callback
        self.add_item(self.accept_button)

        self.decline_button = Button(label="❌ Ablehnen", style=ButtonStyle.danger)
        self.decline_button.callback = self.decline_callback
        self.add_item(self.decline_button)

    async def accept_callback(self, interaction: Interaction):
        await self.disable_buttons(interaction)

        user_id = str(interaction.user.id)
        tournament = load_tournament_data()
        match = next((m for m in tournament.get("matches", []) if m.get("match_id") == self.match_id), None)

        if not match:
            await smart_send(interaction, content="🚫 Match nicht gefunden.", ephemeral=True)
            return

        team1_members = extract_ids(tournament.get("teams", {}).get(match.get("team1"), {}).get("members", []))
        team2_members = extract_ids(tournament.get("teams", {}).get(match.get("team2"), {}).get("members", []))

        if user_id not in team1_members and user_id not in team2_members:
            await smart_send(interaction, content="🚫 Du bist nicht an diesem Match beteiligt.", ephemeral=True)
            return

        self.accepted_by.add(user_id)
        logger.info(f"[RESCHEDULE] Spieler {interaction.user.display_name} ({interaction.user.id}) hat die Reschedule-Anfrage für Match {self.match_id} akzeptiert.")
        await smart_send(interaction, content="✅ Deine Zustimmung wurde gespeichert.", ephemeral=True)

        if (any(member in self.accepted_by for member in team1_members) and
            any(member in self.accepted_by for member in team2_members)):
            match["status"] = "verschoben"
            save_tournament_data(tournament)
            await interaction.channel.send(f"✅ Match {self.match_id} wurde erfolgreich neu terminiert!")
            logger.info(f"[RESCHEDULE] Match {self.match_id} erfolgreich verschoben.")
            self.stop()

    async def decline_callback(self, interaction: Interaction):
        await self.disable_buttons(interaction)
        logger.info(f"[RESCHEDULE] Spieler {interaction.user.display_name} ({interaction.user.id}) hat die Reschedule-Anfrage für Match {self.match_id} abgelehnt.")

        await interaction.channel.send(f"❌ Die Reschedule-Anfrage für Match {self.match_id} wurde abgelehnt!")
        await smart_send(interaction, content="🚫 Du hast die Anfrage abgelehnt.", ephemeral=True)
        logger.info(f"[RESCHEDULE] Match {self.match_id} - Anfrage abgelehnt.")
        self.stop()

    async def disable_buttons(self, interaction: Interaction):
        for child in self.children:
            if isinstance(child, Button):
                child.disabled = True
        await interaction.message.edit(view=self)


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
# Helper: DMs schicken
# ---------------------------------------

async def notify_team_members(interaction: Interaction, team1_members, team2_members, requesting_team, opponent_team, neuer_zeitpunkt, match_id: int):
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
                embed = create_embed_from_config("reminder_embed")
                embed.title = "🔄 Reschedule-Anfrage"
                embed.description = (
                    f"**{requesting_team}** möchte das Match gegen **{opponent_team}** verschieben.\n\n"
                    f"📅 Neuer vorgeschlagener Termin: **{neuer_zeitpunkt.strftime('%d.%m.%Y %H:%M')} Uhr**\n\n"
                    f"Bitte klicke auf einen Button, um zuzustimmen oder abzulehnen!"
                )

                view = RescheduleView(match_id, requesting_team, opponent_team)
                await user.send(embed=embed, view=view)

            except Exception as e:
                logger.warning(f"[RESCHEDULE] Konnte DM an {user.display_name} ({user.id}) nicht senden: {e}")
                failed = True

    return failed  # True wenn mindestens eine DM fehlgeschlagen ist

# ---------------------------------------
# Command: /request_reschedule
# ---------------------------------------

@app_commands.command(name="request_reschedule", description="Fordere eine Neuansetzung für ein Match an.")
@app_commands.describe(
    match_id="Match, das du verschieben möchtest",
    neuer_zeitpunkt="Wunschtermin im Format TT.MM.JJJJ HH:MM"
)
async def request_reschedule(interaction: Interaction, match_id: int, neuer_zeitpunkt: str):
    tournament = load_tournament_data()
    user_id = str(interaction.user.id)
    team_name = get_player_team(user_id)

    if not team_name:
        await smart_send(interaction, content="🚫 Du bist in keinem Team registriert.", ephemeral=True)
        return

    open_matches = get_team_open_matches(team_name)
    if match_id not in [m["match_id"] for m in open_matches]:
        await smart_send(interaction, content="🚫 Du kannst nur Matches deines Teams verschieben.", ephemeral=True)
        return

    match = next((m for m in tournament.get("matches", []) if m.get("match_id") == match_id), None)
    if not match:
        await smart_send(interaction, content="🚫 Match nicht gefunden.", ephemeral=True)
        return

    # Versuche Datum zu parsen
    try:
        parsed_datetime = datetime.strptime(neuer_zeitpunkt, "%d.%m.%Y %H:%M")
    except ValueError:
        await smart_send(interaction, content="🚫 Ungültiges Format! Bitte benutze **TT.MM.JJJJ HH:MM**.", ephemeral=True)
        return

    opponent_team = match["team2"] if match["team1"] == team_name else match["team1"]

    guild = interaction.guild
    if not guild:
        await smart_send(interaction, content="🚫 Fehler: Dieser Befehl geht nur auf einem Server.", ephemeral=True)
        return

    team1_members = tournament.get("teams", {}).get(match.get("team1"), {}).get("members", [])
    team2_members = tournament.get("teams", {}).get(match.get("team2"), {}).get("members", [])

    # ➔ Schritt 1: DMs an alle betroffenen Spieler schicken
    await notify_team_members(interaction, team1_members, team2_members, team_name, opponent_team, parsed_datetime, match_id)

    # ➔ Schritt 2: IMMER Embed + Buttons im Reschedule-Channel posten
    channel = guild.get_channel(RESCHEDULE_CHANNEL_ID)
    if channel:
        embed = create_embed_from_config("reminder_embed")
        embed.title = "🔄 Reschedule-Anfrage"
        embed.description = (
            f"**{team_name}** möchte das Match gegen **{opponent_team}** verschieben.\n\n"
            f"📆 Neuer Vorschlag: **{parsed_datetime.strftime('%d.%m.%Y %H:%M')} Uhr**\n\n"
            f"Bitte akzeptiert oder lehnt ab!"
        )
        view = RescheduleView(match_id, team_name, opponent_team)
        await channel.send(embed=embed, view=view)
        logger.info(f"[RESCHEDULE] Nachricht im Channel #{channel.name} gesendet.")

    # ➔ Schritt 3: Bestätigung an den Command-User
    await smart_send(interaction, content="✅ Reschedule-Anfrage wurde verarbeitet und veröffentlicht.", ephemeral=True)
    logger.info(f"[RESCHEDULE] {team_name} hat eine Reschedule-Anfrage für Match {match_id} gestellt.")

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
    return [
        app_commands.Choice(
            name=f"Match {m['match_id']}: {m['team1']} vs {m['team2']}",
            value=m['match_id']
        )
        for m in open_matches if current in str(m["match_id"])
    ]

# ---------------------------------------
# Helper: Autocomplete für neue Terminwahl
# ---------------------------------------

@request_reschedule.autocomplete("neuer_zeitpunkt")
async def neuer_zeitpunkt_autocomplete(interaction: Interaction, current: str):
    tournament = load_tournament_data()
    registration_end = datetime.fromisoformat(tournament.get("registration_end"))
    tournament_end = datetime.fromisoformat(tournament.get("tournament_end"))

    # Alle Slots generieren
    all_slots = generate_weekend_slots(registration_end, tournament_end)

    # Schon belegte Slots raussuchen
    booked_slots = set()
    for match in tournament.get("matches", []):
        if match.get("scheduled_time"):
            booked_slots.add(match["scheduled_time"])

    # Freie Slots herausfiltern
    free_slots = [slot for slot in all_slots if slot not in booked_slots]

    # Wenn user etwas eingibt (current), filtere die Slots ein bisschen
    if current:
        free_slots = [slot for slot in free_slots if current in slot]

    # Wandle in Choice-Objekte um
    choices = []
    for slot in free_slots[:25]:  # Discord erlaubt max 25 Choices
        dt = datetime.fromisoformat(slot)
        label = f"{dt.strftime('%A')} {dt.strftime('%d.%m.%Y %H:%M')} Uhr"
        value = dt.strftime('%d.%m.%Y %H:%M')  # User gibt später diese Eingabe zurück
        choices.append(app_commands.Choice(name=label, value=value))

    return choices
