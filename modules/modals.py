# modules/modals.py

import discord
from discord import Interaction
from discord.ui import Modal, Select, TextInput, View

# Lokale Modules
from modules.dataStorage import add_game, load_tournament_data, save_tournament_data
from modules.logger import logger
from modules.utils import (
    generate_team_name,
    validate_date,
    validate_string,
    validate_time_range,
)

### Helper function


def find_member(guild, search_str):
    # Versuche erstmal als Mention/ID
    search_str = search_str.strip()
    # Erwähnung: <@12345>
    if search_str.startswith("<@") and search_str.endswith(">"):
        user_id = int("".join(filter(str.isdigit, search_str)))
        return guild.get_member(user_id)
    # Reine User-ID
    if search_str.isdigit():
        return guild.get_member(int(search_str))
    # Name#Discriminator
    if "#" in search_str:
        name, discrim = search_str.split("#", 1)
        for m in guild.members:
            if m.name.lower() == name.lower() and m.discriminator == discrim:
                return m
    # Displayname Case-Insensitive (Fuzzy)
    for m in guild.members:
        if m.display_name.lower() == search_str.lower() or m.name.lower() == search_str.lower():
            return m
    # Optional: Fuzzy-Match (z.B. Levenshtein)
    return None


class TestModal(discord.ui.Modal, title="Test funktioniert?"):
    test = discord.ui.TextInput(label="Ein Testfeld")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()


class TeamFullJoinModal(Modal):
    def __init__(self):
        super().__init__(title="Team-Anmeldung")

        self.team_name = TextInput(
            label="Teamname",
            required=False,
            placeholder="Freilassen für Zufällig",
            max_length=32,
        )
        self.mitspieler_field = TextInput(
            label="Mitspieler (nur Name, keine ID/Tag/@)",
            required=False,
            placeholder="z.B. Aldemar",
            max_length=32,
        )
        self.samstag_zeit = TextInput(
            label="Verfügbarkeit Samstag (z.B. 12:00-18:00)",
            required=True,
            placeholder="12:00-18:00",
            max_length=20,
        )
        self.sonntag_zeit = TextInput(
            label="Verfügbarkeit Sonntag (z.B. 12:00-18:00)",
            required=True,
            placeholder="12:00-18:00",
            max_length=20,
        )
        self.unavailable_dates = TextInput(
            label="Blockierte Tage (YYYY-MM-DD)",
            required=False,
            placeholder="2025-06-01, 2025-06-08",
            max_length=200,
        )

        self.add_item(self.team_name)
        self.add_item(self.mitspieler_field)
        self.add_item(self.samstag_zeit)
        self.add_item(self.sonntag_zeit)
        self.add_item(self.unavailable_dates)

    async def on_submit(self, interaction: Interaction):
        team_name = self.team_name.value.strip() or generate_team_name()
        mitspieler_name = self.mitspieler_field.value.strip()
        samstag = self.samstag_zeit.value.strip()
        sonntag = self.sonntag_zeit.value.strip()
        unavailable_raw = self.unavailable_dates.value.strip().replace("\n", ",").replace(" ", "")
        unavailable_list = [d for d in unavailable_raw.split(",") if d] if unavailable_raw else []

        # Teamname validieren
        is_valid, err = validate_string(team_name, max_length=32)
        if not is_valid:
            await interaction.response.send_message(f"❌ Teamname ungültig: {err}", ephemeral=True)
            return

        # Zeiten validieren
        valid, err = validate_time_range(samstag)
        if not valid:
            await interaction.response.send_message(f"❌ Fehler bei Samstag: {err}", ephemeral=True)
            return
        valid, err = validate_time_range(sonntag)
        if not valid:
            await interaction.response.send_message(f"❌ Fehler bei Sonntag: {err}", ephemeral=True)
            return

        # Blockierte Tage validieren
        for d in unavailable_list:
            valid, err = validate_date(d)
            if not valid:
                await interaction.response.send_message(f"❌ {err}", ephemeral=True)
                return

        tournament = load_tournament_data()
        if mitspieler_name:
            # Mitspieler suchen
            mitspieler = None
            for m in interaction.guild.members:
                if m.display_name.lower() == mitspieler_name.lower() or m.name.lower() == mitspieler_name.lower():
                    mitspieler = m
                    break
            if not mitspieler:
                await interaction.response.send_message(
                    "❌ Mitspieler nicht gefunden! Bitte exakt den Namen angeben.",
                    ephemeral=True,
                )
                return

            # TEAM-Anmeldung
            teams = tournament.setdefault("teams", {})
            teams[team_name] = {
                "members": [interaction.user.mention, mitspieler.mention],
                "verfügbarkeit": {"samstag": samstag, "sonntag": sonntag},
                "unavailable_dates": unavailable_list,
            }
            save_tournament_data(tournament)
            await interaction.response.send_message(
                f"✅ Team-Anmeldung gespeichert für **{team_name}**!\n"
                f"Mitspieler: {mitspieler.mention}\n"
                f"Samstag: {samstag}\nSonntag: {sonntag}\n"
                f"Blockierte Tage: {', '.join(unavailable_list) if unavailable_list else 'Keine'}",
                ephemeral=True,
            )
        else:
            # SOLO-Anmeldung
            solo_list = tournament.setdefault("solo", [])
            # Prüfe, ob der User schon Solo ist!
            if any(entry.get("player") == interaction.user.mention for entry in solo_list):
                await interaction.response.send_message(
                    "❗ Du bist bereits als Solo-Spieler angemeldet.", ephemeral=True
                )
                return
            solo_entry = {
                "player": interaction.user.mention,
                "verfügbarkeit": {"samstag": samstag, "sonntag": sonntag},
                "unavailable_dates": unavailable_list,
            }
            solo_list.append(solo_entry)
            save_tournament_data(tournament)
            await interaction.response.send_message(
                f"✅ Solo-Anmeldung gespeichert!\n"
                f"Samstag: {samstag}\nSonntag: {sonntag}\n"
                f"Blockierte Tage: {', '.join(unavailable_list) if unavailable_list else 'Keine'}",
                ephemeral=True,
            )


class AddGameModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Neues Spiel hinzufügen")

        self.name = discord.ui.TextInput(label="Anzeigename", max_length=50)
        self.genre = discord.ui.TextInput(label="Genre (z.B. MOBA, Denkspiel)", max_length=30)
        self.platform = discord.ui.TextInput(label="Plattform", placeholder="PC", max_length=20)
        self.team_size = discord.ui.TextInput(label="Teamgröße pro Team", placeholder="1")
        self.match_duration = discord.ui.TextInput(label="Matchdauer in Minuten", placeholder="60")

        self.add_item(self.name)
        self.add_item(self.genre)
        self.add_item(self.platform)
        self.add_item(self.team_size)
        self.add_item(self.match_duration)

    async def validate_input(self, interaction: discord.Interaction):
        is_valid, error_message = validate_time_range(self.time_range.value)
        if not is_valid:
            await interaction.response.send_message(f"❌ {error_message}", ephemeral=True)
            raise ValueError(error_message)


    async def on_submit(self, interaction: discord.Interaction):
        logger.debug(f"[DEBUG] Eingaben: {self.name.value}, {self.genre.value}, {self.platform.value}, {self.team_size.value}, {self.match_duration.value}")
        try:
            team_size_int = int(self.team_size.value)
            duration = int(self.match_duration.value)

            game_id = self.name.value.strip().replace(" ", "_")

            add_game(
                game_id=game_id,
                name=self.name.value.strip(),
                genre=self.genre.value.strip(),
                platform=self.platform.value.strip(),
                match_duration_minutes=duration,
                pause_minutes=30,
                min_players_per_team=team_size_int,
                max_players_per_team=team_size_int,
                emoji="🎮"
            )

            logger.debug(f"[DEBUG] Spiel wurde erfolgreich verarbeitet.")

            await interaction.response.send_message(
                f"✅ Spiel **{self.name.value}** wurde gespeichert als `{game_id}`.",
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"[ADD_GAME_MODAL] Fehler im on_submit: {e}")
            await interaction.response.send_message(f"❌ Fehler beim Speichern: {e}", ephemeral=True)


class StartTournamentModal(discord.ui.Modal, title="Turnier starten"):
    poll_duration = TextInput(
        label="Dauer der Umfrage (in Stunden)",
        placeholder="z. B. 48",
        required=True,
        default="48",
        max_length=3,
    )

    registration_duration = TextInput(
        label="Dauer der Anmeldung (in Stunden)",
        placeholder="z. B. 72",
        required=True,
        default="72",
        max_length=3,
    )

    tournament_weeks = TextInput(
        label="Turnierlaufzeit (in Wochen)",
        placeholder="z. B. 1",
        required=True,
        default="1",
        max_length=2,
    )

    team_size = TextInput(
        label="Spieler pro Team",
        placeholder="z. B. 2",
        required=True,
        default="2",
        max_length=2,
    )

    def __init__(self, interaction: discord.Interaction):
        super().__init__()
        self.interaction = interaction

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)

            # Werte parsen
            poll_h = int(self.poll_duration.value)
            reg_h = int(self.registration_duration.value)
            weeks = int(self.tournament_weeks.value)
            team_size = int(self.team_size.value)

            # Weiterleitung zur Start-Logik
            from modules.admin_tools import handle_start_tournament_modal

            await handle_start_tournament_modal(
                interaction,
                poll_duration=poll_h,
                registration_duration=reg_h,
                tournament_weeks=weeks,
                team_size=team_size,
            )

        except ValueError:
            await interaction.response.send_message(
                "❌ Ungültige Eingabe. Bitte gib überall ganze Zahlen ein.",
                ephemeral=True,
            )


