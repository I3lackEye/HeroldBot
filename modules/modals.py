# modules/modals.py

import discord
from discord import Interaction
from discord.ui import Modal, Select, TextInput, View

# Local modules
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
    """
    Searches for a member in the guild by mention, ID, name#discriminator, or display name.

    :param guild: Discord guild to search in
    :param search_str: Search string (mention, ID, or name)
    :return: Member object or None if not found
    """
    search_str = search_str.strip()
    # Mention: <@12345>
    if search_str.startswith("<@") and search_str.endswith(">"):
        user_id = int("".join(filter(str.isdigit, search_str)))
        return guild.get_member(user_id)
    # Pure user ID
    if search_str.isdigit():
        return guild.get_member(int(search_str))
    # Name#Discriminator
    if "#" in search_str:
        name, discrim = search_str.split("#", 1)
        for m in guild.members:
            if m.name.lower() == name.lower() and m.discriminator == discrim:
                return m
    # Display name Case-Insensitive (Fuzzy)
    for m in guild.members:
        if m.display_name.lower() == search_str.lower() or m.name.lower() == search_str.lower():
            return m
    # Optional: Fuzzy-Match (e.g. Levenshtein)
    return None


class TestModal(discord.ui.Modal, title="Test works?"):
    """Simple test modal for debugging."""
    test = discord.ui.TextInput(label="A test field")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()


class TeamFullJoinModal(Modal):
    """Modal for team registration with availability and teammate selection."""

    def __init__(self):
        super().__init__(title="Team Registration")

        self.team_name = TextInput(
            label="Team Name",
            required=False,
            placeholder="Leave empty for random",
            max_length=32,
        )
        self.teammate_field = TextInput(
            label="Teammate (only name, no ID/Tag/@)",
            required=False,
            placeholder="e.g. Aldemar",
            max_length=32,
        )
        self.saturday_time = TextInput(
            label="Saturday Availability (e.g. 12:00-18:00)",
            required=True,
            placeholder="12:00-18:00",
            max_length=20,
        )
        self.sunday_time = TextInput(
            label="Sunday Availability (e.g. 12:00-18:00)",
            required=True,
            placeholder="12:00-18:00",
            max_length=20,
        )
        self.unavailable_dates = TextInput(
            label="Blocked Days (YYYY-MM-DD)",
            required=False,
            placeholder="2025-06-01, 2025-06-08",
            max_length=200,
        )

        self.add_item(self.team_name)
        self.add_item(self.teammate_field)
        self.add_item(self.saturday_time)
        self.add_item(self.sunday_time)
        self.add_item(self.unavailable_dates)

    async def on_submit(self, interaction: Interaction):
        """Processes team registration submission."""
        team_name = self.team_name.value.strip() or generate_team_name()
        teammate_name = self.teammate_field.value.strip()
        saturday = self.saturday_time.value.strip()
        sunday = self.sunday_time.value.strip()
        unavailable_raw = self.unavailable_dates.value.strip().replace("\n", ",").replace(" ", "")
        unavailable_list = [d for d in unavailable_raw.split(",") if d] if unavailable_raw else []

        # Validate team name
        is_valid, err = validate_string(team_name, max_length=32)
        if not is_valid:
            await interaction.response.send_message(f"❌ Invalid team name: {err}", ephemeral=True)
            return

        # Validate times
        valid, err = validate_time_range(saturday)
        if not valid:
            await interaction.response.send_message(f"❌ Error with Saturday: {err}", ephemeral=True)
            return
        valid, err = validate_time_range(sunday)
        if not valid:
            await interaction.response.send_message(f"❌ Error with Sunday: {err}", ephemeral=True)
            return

        # Validate blocked days
        for d in unavailable_list:
            valid, err = validate_date(d)
            if not valid:
                await interaction.response.send_message(f"❌ {err}", ephemeral=True)
                return

        tournament = load_tournament_data()
        if teammate_name:
            # Search for teammate
            teammate = None
            for m in interaction.guild.members:
                if m.display_name.lower() == teammate_name.lower() or m.name.lower() == teammate_name.lower():
                    teammate = m
                    break
            if not teammate:
                await interaction.response.send_message(
                    "❌ Teammate not found! Please enter the exact name.",
                    ephemeral=True,
                )
                return

            # TEAM registration
            teams = tournament.setdefault("teams", {})
            teams[team_name] = {
                "members": [interaction.user.mention, teammate.mention],
                "availability": {"saturday": saturday, "sunday": sunday},
                "unavailable_dates": unavailable_list,
            }
            save_tournament_data(tournament)
            await interaction.response.send_message(
                f"✅ Team registration saved for **{team_name}**!\n"
                f"Teammate: {teammate.mention}\n"
                f"Saturday: {saturday}\nSunday: {sunday}\n"
                f"Blocked days: {', '.join(unavailable_list) if unavailable_list else 'None'}",
                ephemeral=True,
            )
        else:
            # SOLO registration
            solo_list = tournament.setdefault("solo", [])
            # Check if user is already solo!
            if any(entry.get("player") == interaction.user.mention for entry in solo_list):
                await interaction.response.send_message(
                    "❗ You are already registered as a solo player.", ephemeral=True
                )
                return
            solo_entry = {
                "player": interaction.user.mention,
                "availability": {"saturday": saturday, "sunday": sunday},
                "unavailable_dates": unavailable_list,
            }
            solo_list.append(solo_entry)
            save_tournament_data(tournament)
            await interaction.response.send_message(
                f"✅ Solo registration saved!\n", ephemeral=True,)


class AddGameModal(discord.ui.Modal):
    """Modal for adding a new game to the game pool."""

    def __init__(self):
        super().__init__(title="Add New Game")

        self.name = discord.ui.TextInput(label="Display Name", max_length=50)
        self.genre = discord.ui.TextInput(label="Genre (e.g. MOBA, Puzzle)", max_length=30)
        self.platform = discord.ui.TextInput(label="Platform", placeholder="PC", max_length=20)
        self.team_size = discord.ui.TextInput(label="Team Size per Team", placeholder="1")
        self.match_duration = discord.ui.TextInput(label="Match Duration in Minutes", placeholder="60")

        self.add_item(self.name)
        self.add_item(self.genre)
        self.add_item(self.platform)
        self.add_item(self.team_size)
        self.add_item(self.match_duration)

    async def validate_input(self, interaction: discord.Interaction):
        """Validates time range input."""
        is_valid, error_message = validate_time_range(self.time_range.value)
        if not is_valid:
            await interaction.response.send_message(f"❌ {error_message}", ephemeral=True)
            raise ValueError(error_message)


    async def on_submit(self, interaction: discord.Interaction):
        """Processes game addition submission."""
        logger.debug(f"[DEBUG] Input: {self.name.value}, {self.genre.value}, {self.platform.value}, {self.team_size.value}, {self.match_duration.value}")
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

            logger.debug(f"[DEBUG] Game was successfully processed.")

            await interaction.response.send_message(
                f"✅ Game **{self.name.value}** was saved as `{game_id}`.",
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"[ADD_GAME_MODAL] Error in on_submit: {e}")
            await interaction.response.send_message(f"❌ Error saving: {e}", ephemeral=True)


class StartTournamentModal(discord.ui.Modal, title="Start Tournament"):
    """Modal for configuring and starting a new tournament."""

    poll_duration = TextInput(
        label="Poll Duration (in hours)",
        placeholder="e.g. 48",
        required=True,
        default="48",
        max_length=3,
    )

    registration_duration = TextInput(
        label="Registration Duration (in hours)",
        placeholder="e.g. 72",
        required=True,
        default="72",
        max_length=3,
    )

    tournament_weeks = TextInput(
        label="Tournament Duration (in weeks)",
        placeholder="e.g. 1",
        required=True,
        default="1",
        max_length=2,
    )

    team_size = TextInput(
        label="Players per Team",
        placeholder="e.g. 2",
        required=True,
        default="2",
        max_length=2,
    )

    def __init__(self, interaction: discord.Interaction):
        super().__init__()
        self.interaction = interaction

    async def on_submit(self, interaction: discord.Interaction):
        """Processes tournament start submission."""
        try:
            await interaction.response.defer(ephemeral=True)

            # Parse values
            poll_h = int(self.poll_duration.value)
            reg_h = int(self.registration_duration.value)
            weeks = int(self.tournament_weeks.value)
            team_size = int(self.team_size.value)

            # Forward to start logic
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
                "❌ Invalid input. Please enter whole numbers everywhere.",
                ephemeral=True,
            )
