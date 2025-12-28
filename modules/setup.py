# modules/setup.py

import json
import os
from typing import Optional

import discord
from discord import Interaction, app_commands, TextChannel, Role, ButtonStyle
from discord.ext import commands
from discord.ui import Modal, TextInput, View, Button

from modules.logger import logger
from modules.utils import has_permission


class SetupModal(Modal, title="🎮 HeroldBot Setup"):
    """Modal for collecting bot configuration."""

    limits_channel = TextInput(
        label="Limits Channel",
        placeholder="#limits or Channel ID",
        required=True,
        max_length=100
    )

    reminder_channel = TextInput(
        label="Reminder Channel",
        placeholder="#reminder or Channel ID",
        required=True,
        max_length=100
    )

    reschedule_channel = TextInput(
        label="Reschedule Channel",
        placeholder="#reschedule or Channel ID",
        required=True,
        max_length=100
    )

    winner_role = TextInput(
        label="Champion/Winner Role",
        placeholder="@Champion or Role ID",
        required=True,
        max_length=100
    )

    timezone = TextInput(
        label="Timezone (optional)",
        placeholder="Europe/Berlin",
        required=False,
        default="Europe/Berlin",
        max_length=50
    )

    async def on_submit(self, interaction: Interaction):
        """Process setup submission."""
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        errors = []
        config_data = {}

        # Parse and validate limits channel
        limits_ch = await self._parse_channel(guild, self.limits_channel.value)
        if limits_ch:
            config_data["limits_channel"] = str(limits_ch.id)
        else:
            errors.append(f"❌ Limits channel not found: `{self.limits_channel.value}`")

        # Parse and validate reminder channel
        reminder_ch = await self._parse_channel(guild, self.reminder_channel.value)
        if reminder_ch:
            config_data["reminder_channel"] = str(reminder_ch.id)
        else:
            errors.append(f"❌ Reminder channel not found: `{self.reminder_channel.value}`")

        # Parse and validate reschedule channel
        reschedule_ch = await self._parse_channel(guild, self.reschedule_channel.value)
        if reschedule_ch:
            config_data["reschedule_channel"] = str(reschedule_ch.id)
        else:
            errors.append(f"❌ Reschedule channel not found: `{self.reschedule_channel.value}`")

        # Parse and validate winner role
        winner_role = await self._parse_role(guild, self.winner_role.value)
        if winner_role:
            config_data["winner_role"] = str(winner_role.id)
        else:
            errors.append(f"❌ Winner role not found: `{self.winner_role.value}`")

        # Validate timezone (basic check)
        tz_value = self.timezone.value.strip() or "Europe/Berlin"
        config_data["timezone"] = tz_value

        # If errors, show them
        if errors:
            error_msg = "**Setup Errors:**\n" + "\n".join(errors)
            error_msg += "\n\n**Tip:** Use channel mentions (#channel) or IDs, and role mentions (@role) or IDs."
            await interaction.followup.send(error_msg, ephemeral=True)
            return

        # Save configuration
        try:
            await self._save_config(config_data)

            success_msg = (
                "✅ **Bot successfully configured!**\n\n"
                f"📍 **Limits Channel:** <#{config_data['limits_channel']}>\n"
                f"📍 **Reminder Channel:** <#{config_data['reminder_channel']}>\n"
                f"📍 **Reschedule Channel:** <#{config_data['reschedule_channel']}>\n"
                f"🏆 **Winner Role:** <@&{config_data['winner_role']}>\n"
                f"🕒 **Timezone:** {config_data['timezone']}\n\n"
                f"The bot is now ready to use! 🎉"
            )
            await interaction.followup.send(success_msg, ephemeral=False)
            logger.info(f"[SETUP] Bot configured successfully by {interaction.user.display_name}")

        except Exception as e:
            logger.error(f"[SETUP] Error saving config: {e}")
            await interaction.followup.send(
                f"❌ Error saving configuration: {str(e)}\n"
                f"Please check logs and try again.",
                ephemeral=True
            )

    async def _parse_channel(self, guild: discord.Guild, value: str) -> Optional[TextChannel]:
        """Parse channel from mention or ID."""
        value = value.strip()

        # Try as mention first
        if value.startswith("<#") and value.endswith(">"):
            channel_id = value[2:-1]
            channel = guild.get_channel(int(channel_id))
            return channel if isinstance(channel, TextChannel) else None

        # Try as ID
        try:
            channel = guild.get_channel(int(value))
            return channel if isinstance(channel, TextChannel) else None
        except ValueError:
            pass

        # Try as name
        channel = discord.utils.get(guild.text_channels, name=value)
        return channel

    async def _parse_role(self, guild: discord.Guild, value: str) -> Optional[Role]:
        """Parse role from mention or ID."""
        value = value.strip()

        # Try as mention first
        if value.startswith("<@&") and value.endswith(">"):
            role_id = value[3:-1]
            return guild.get_role(int(role_id))

        # Try as ID
        try:
            return guild.get_role(int(value))
        except ValueError:
            pass

        # Try as name
        return discord.utils.get(guild.roles, name=value)

    async def _save_config(self, data: dict):
        """Save configuration to bot.json."""
        config_path = "configs/bot.json"

        # Load existing config
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        else:
            # Create default config structure
            config = {
                "data_paths": {
                    "data": "data/data.json",
                    "tournament": "data/tournament.json"
                },
                "channels": {},
                "roles": {
                    "moderator": [],
                    "admin": [],
                    "dev": [],
                    "winner": []
                },
                "language": "de",
                "timezone": "Europe/Berlin",
                "max_string_length": 50
            }

        # Update with new data
        config["channels"]["limits"] = data["limits_channel"]
        config["channels"]["reminder"] = data["reminder_channel"]
        config["channels"]["reschedule"] = data["reschedule_channel"]
        config["roles"]["winner"] = [data["winner_role"]]
        config["timezone"] = data["timezone"]

        # Save back to file
        os.makedirs("configs", exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        logger.info(f"[SETUP] Configuration saved to {config_path}")


class SetupView(View):
    """View with Start Setup button."""

    def __init__(self):
        super().__init__(timeout=300)  # 5 minutes

    @discord.ui.button(label="🚀 Start Setup", style=ButtonStyle.primary)
    async def start_setup(self, interaction: Interaction, button: Button):
        """Show setup modal when button clicked."""
        modal = SetupModal()
        await interaction.response.send_modal(modal)
        self.stop()


class SetupCommands(app_commands.Group):
    """Setup command group."""

    def __init__(self):
        super().__init__(name="setup", description="Bot setup and configuration")

    @app_commands.command(
        name="start",
        description="Start interactive bot setup"
    )
    async def setup_start(self, interaction: Interaction):
        """Start the interactive setup wizard."""
        if not has_permission(interaction.user, "Admin"):
            await interaction.response.send_message(
                "🚫 You need Admin permissions to run setup.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🎮 Welcome to HeroldBot Setup!",
            description=(
                "This wizard will help you configure the bot for your server.\n\n"
                "**You will configure:**\n"
                "📍 Limits Channel\n"
                "📍 Reminder Channel\n"
                "📍 Reschedule Channel\n"
                "🏆 Champion/Winner Role\n"
                "🕒 Timezone\n\n"
                "Click **Start Setup** below to begin."
            ),
            color=0x5865F2
        )
        embed.set_footer(text="You can run this setup again anytime with /setup start")

        view = SetupView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)


class SetupCog(commands.Cog):
    """Cog for setup commands."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        """Called when cog is loaded."""
        # Add setup group to tree
        self.bot.tree.add_command(SetupCommands())


async def setup(bot: commands.Bot):
    """Setup function for cog loading."""
    await bot.add_cog(SetupCog(bot))
