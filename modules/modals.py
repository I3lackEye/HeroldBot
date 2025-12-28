# modules/modals.py

import discord
from discord import Interaction
from discord.ui import Modal, Select, TextInput, View
from typing import Optional, Tuple

# Local modules
from modules.dataStorage import add_game, load_tournament_data, save_tournament_data
from modules.logger import logger
from modules.utils import (
    generate_team_name,
    validate_date,
    validate_string,
    validate_time_range,
)


# =======================================
# MODAL VALIDATION HELPER CLASS
# =======================================

class ModalValidator:
    """
    Centralized validation logic for Discord modals.
    Provides consistent error messages and validation across all modals.
    """

    @staticmethod
    def validate_integer(value: str, min_val: int = None, max_val: int = None, field_name: str = "Value") -> Tuple[bool, Optional[int], Optional[str]]:
        """
        Validates an integer input with optional range checking.

        :param value: String value to validate
        :param min_val: Minimum allowed value (inclusive)
        :param max_val: Maximum allowed value (inclusive)
        :param field_name: Name of the field for error messages
        :return: (is_valid, parsed_value, error_message)
        """
        try:
            int_val = int(value.strip())
        except (ValueError, AttributeError):
            return False, None, f"{field_name} must be a whole number."

        if min_val is not None and int_val < min_val:
            return False, None, f"{field_name} must be at least {min_val}."

        if max_val is not None and int_val > max_val:
            return False, None, f"{field_name} must be at most {max_val}."

        return True, int_val, None

    @staticmethod
    def check_registration_open(tournament: dict) -> Tuple[bool, Optional[str]]:
        """
        Checks if tournament registration is currently open.

        :param tournament: Tournament data dict
        :return: (is_open, error_message)
        """
        if not tournament.get("running", False):
            return False, "❌ No tournament is currently running."

        if not tournament.get("registration_open", True):
            return False, "❌ Registration is closed. You can no longer join the tournament."

        return True, None

    @staticmethod
    def check_duplicate_registration(user_mention: str, tournament: dict) -> Tuple[bool, Optional[str]]:
        """
        Checks if user is already registered (in team or solo).

        :param user_mention: User mention string (e.g., "<@123456>")
        :param tournament: Tournament data dict
        :return: (is_duplicate, error_message with location)
        """
        # Check if in any team
        teams = tournament.get("teams", {})
        for team_name, team_data in teams.items():
            if user_mention in team_data.get("members", []):
                return True, f"❌ You are already registered in team **{team_name}**."

        # Check if in solo list
        solo_list = tournament.get("solo", [])
        if any(entry.get("player") == user_mention for entry in solo_list):
            return True, "❌ You are already registered as a solo player."

        return False, None

    @staticmethod
    def validate_teammate(teammate_name: str, guild, requester_id: int, tournament: dict) -> Tuple[bool, Optional[discord.Member], Optional[str]]:
        """
        Validates teammate selection with comprehensive checks.

        :param teammate_name: Name entered by user
        :param guild: Discord guild
        :param requester_id: ID of the user making the request
        :param tournament: Tournament data dict
        :return: (is_valid, member_object, error_message)
        """
        if not teammate_name or not teammate_name.strip():
            return False, None, None  # No teammate = solo registration

        teammate_name = teammate_name.strip()

        # Find teammate
        teammate = None
        for m in guild.members:
            if m.display_name.lower() == teammate_name.lower() or m.name.lower() == teammate_name.lower():
                teammate = m
                break

        if not teammate:
            return False, None, f"❌ Teammate **{teammate_name}** not found. Please check the spelling."

        # Check if trying to register with yourself
        if teammate.id == requester_id:
            return False, None, "❌ You cannot register with yourself as a teammate!"

        # Check if teammate is already registered
        teams = tournament.get("teams", {})
        for team_name, team_data in teams.items():
            if teammate.mention in team_data.get("members", []):
                return False, None, f"❌ {teammate.mention} is already in team **{team_name}**."

        solo_list = tournament.get("solo", [])
        if any(entry.get("player") == teammate.mention for entry in solo_list):
            return False, None, f"❌ {teammate.mention} is already registered as a solo player."

        return True, teammate, None

    @staticmethod
    def validate_team_name(team_name: str, tournament: dict) -> Tuple[bool, str, Optional[str]]:
        """
        Validates team name and ensures uniqueness.

        :param team_name: Requested team name (can be empty for random)
        :param tournament: Tournament data dict
        :return: (is_valid, final_team_name, error_message)
        """
        if not team_name or not team_name.strip():
            # Generate random name
            return True, generate_team_name(), None

        team_name = team_name.strip()

        # Validate format
        is_valid, err = validate_string(team_name, max_length=32)
        if not is_valid:
            return False, "", f"❌ Invalid team name: {err}"

        # Check uniqueness
        teams = tournament.get("teams", {})
        if team_name in teams:
            return False, "", f"❌ Team name **{team_name}** is already taken. Please choose another."

        return True, team_name, None


# =======================================
# HELPER FUNCTIONS
# =======================================

def find_member(guild, search_str):
    """
    Searches for a member in the guild by mention, ID, or name.

    :param guild: Discord guild to search in
    :param search_str: Search string (mention, ID, or name)
    :return: Member object or None if not found
    """
    if not search_str:
        return None

    search_str = search_str.strip()

    # Mention: <@12345> or <@!12345>
    if search_str.startswith("<@") and search_str.endswith(">"):
        try:
            digits = "".join(filter(str.isdigit, search_str))
            if digits:
                user_id = int(digits)
                return guild.get_member(user_id)
        except (ValueError, AttributeError):
            pass

    # Pure user ID
    if search_str.isdigit():
        try:
            return guild.get_member(int(search_str))
        except (ValueError, OverflowError):
            pass

    # Display name or username (case-insensitive)
    search_lower = search_str.lower()
    for m in guild.members:
        if m.display_name.lower() == search_lower or m.name.lower() == search_lower:
            return m

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
        """Processes team registration submission with comprehensive validation."""
        # Load tournament data first
        tournament = load_tournament_data()

        # 1. Check tournament state
        is_open, error_msg = ModalValidator.check_registration_open(tournament)
        if not is_open:
            await interaction.response.send_message(error_msg, ephemeral=True)
            return

        # 2. Check for duplicate registration
        is_duplicate, error_msg = ModalValidator.check_duplicate_registration(
            interaction.user.mention, tournament
        )
        if is_duplicate:
            await interaction.response.send_message(error_msg, ephemeral=True)
            return

        # 3. Validate time ranges
        saturday = self.saturday_time.value.strip()
        sunday = self.sunday_time.value.strip()

        valid, err = validate_time_range(saturday)
        if not valid:
            await interaction.response.send_message(f"❌ Error with Saturday: {err}", ephemeral=True)
            return

        valid, err = validate_time_range(sunday)
        if not valid:
            await interaction.response.send_message(f"❌ Error with Sunday: {err}", ephemeral=True)
            return

        # 4. Validate blocked days
        unavailable_raw = self.unavailable_dates.value.strip().replace("\n", ",").replace(" ", "")
        unavailable_list = [d for d in unavailable_raw.split(",") if d] if unavailable_raw else []

        for d in unavailable_list:
            valid, err = validate_date(d)
            if not valid:
                await interaction.response.send_message(f"❌ {err}", ephemeral=True)
                return

        # 5. Validate teammate (if provided)
        teammate_name = self.teammate_field.value.strip() if self.teammate_field.value else ""
        is_valid, teammate, error_msg = ModalValidator.validate_teammate(
            teammate_name, interaction.guild, interaction.user.id, tournament
        )

        if error_msg:  # Error occurred
            await interaction.response.send_message(error_msg, ephemeral=True)
            return

        # 6. Process registration
        if teammate:
            # TEAM registration
            # Validate team name
            requested_name = self.team_name.value.strip() if self.team_name.value else ""
            is_valid, team_name, error_msg = ModalValidator.validate_team_name(
                requested_name, tournament
            )
            if not is_valid:
                await interaction.response.send_message(error_msg, ephemeral=True)
                return

            # Create team
            teams = tournament.setdefault("teams", {})
            teams[team_name] = {
                "members": [interaction.user.mention, teammate.mention],
                "availability": {"saturday": saturday, "sunday": sunday},
                "unavailable_dates": unavailable_list,
            }
            save_tournament_data(tournament)

            await interaction.response.send_message(
                f"✅ Team registration successful!\n"
                f"**Team Name:** {team_name}\n"
                f"**Members:** {interaction.user.mention}, {teammate.mention}\n"
                f"**Saturday:** {saturday}\n"
                f"**Sunday:** {sunday}\n"
                f"**Blocked Days:** {', '.join(unavailable_list) if unavailable_list else 'None'}",
                ephemeral=True,
            )
        else:
            # SOLO registration
            solo_list = tournament.setdefault("solo", [])
            solo_entry = {
                "player": interaction.user.mention,
                "availability": {"saturday": saturday, "sunday": sunday},
                "unavailable_dates": unavailable_list,
            }
            solo_list.append(solo_entry)
            save_tournament_data(tournament)

            await interaction.response.send_message(
                f"✅ Solo registration successful!\n"
                f"**Saturday:** {saturday}\n"
                f"**Sunday:** {sunday}\n"
                f"**Blocked Days:** {', '.join(unavailable_list) if unavailable_list else 'None'}",
                ephemeral=True,
            )


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

    async def on_submit(self, interaction: discord.Interaction):
        """Processes game addition submission with validation."""
        logger.debug(
            f"[ADD_GAME] Input: {self.name.value}, {self.genre.value}, "
            f"{self.platform.value}, {self.team_size.value}, {self.match_duration.value}"
        )

        # Validate team size
        is_valid, team_size_int, error_msg = ModalValidator.validate_integer(
            self.team_size.value, min_val=1, max_val=10, field_name="Team size"
        )
        if not is_valid:
            await interaction.response.send_message(error_msg, ephemeral=True)
            return

        # Validate match duration
        is_valid, duration, error_msg = ModalValidator.validate_integer(
            self.match_duration.value, min_val=5, max_val=300, field_name="Match duration"
        )
        if not is_valid:
            await interaction.response.send_message(error_msg, ephemeral=True)
            return

        # Validate name
        name = self.name.value.strip()
        if not name:
            await interaction.response.send_message(
                "❌ Game name cannot be empty.", ephemeral=True
            )
            return

        try:
            game_id = name.replace(" ", "_")

            add_game(
                game_id=game_id,
                name=name,
                genre=self.genre.value.strip(),
                platform=self.platform.value.strip(),
                match_duration_minutes=duration,
                pause_minutes=30,
                min_players_per_team=team_size_int,
                max_players_per_team=team_size_int,
                emoji="🎮"
            )

            logger.info(f"[ADD_GAME] Game '{name}' saved as '{game_id}'")

            await interaction.response.send_message(
                f"✅ Game **{name}** was saved as `{game_id}`.\n"
                f"**Team Size:** {team_size_int}\n"
                f"**Match Duration:** {duration} minutes",
                ephemeral=True
            )

        except ValueError as e:
            logger.error(f"[ADD_GAME] Validation error: {e}")
            await interaction.response.send_message(f"❌ Validation error: {e}", ephemeral=True)
        except Exception as e:
            logger.error(f"[ADD_GAME] Unexpected error: {e}")
            await interaction.response.send_message(f"❌ Failed to save game: {e}", ephemeral=True)


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
        """Processes tournament start submission with validation."""
        # Validate poll duration (1-168 hours = 1 week max)
        is_valid, poll_h, error_msg = ModalValidator.validate_integer(
            self.poll_duration.value, min_val=1, max_val=168, field_name="Poll duration"
        )
        if not is_valid:
            await interaction.response.send_message(error_msg, ephemeral=True)
            return

        # Validate registration duration (1-336 hours = 2 weeks max)
        is_valid, reg_h, error_msg = ModalValidator.validate_integer(
            self.registration_duration.value, min_val=1, max_val=336, field_name="Registration duration"
        )
        if not is_valid:
            await interaction.response.send_message(error_msg, ephemeral=True)
            return

        # Validate team size (1-10 players)
        is_valid, team_size_val, error_msg = ModalValidator.validate_integer(
            self.team_size.value, min_val=1, max_val=10, field_name="Team size"
        )
        if not is_valid:
            await interaction.response.send_message(error_msg, ephemeral=True)
            return

        try:
            await interaction.response.defer(ephemeral=True)

            # Forward to start logic
            from modules.admin_tools import handle_start_tournament_modal

            await handle_start_tournament_modal(
                interaction,
                poll_duration=poll_h,
                registration_duration=reg_h,
                team_size=team_size_val,
            )

        except Exception as e:
            logger.error(f"[START_TOURNAMENT] Error: {e}")
            await interaction.followup.send(
                f"❌ Failed to start tournament: {e}",
                ephemeral=True,
            )
