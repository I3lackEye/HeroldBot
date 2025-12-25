# modules/info.py

from datetime import datetime

import discord
from discord import Embed, Interaction, app_commands
from discord.ext import commands

# Local modules
from modules.dataStorage import load_tournament_data
from modules.embeds import send_help, send_match_schedule, send_participants_overview
from modules.matchmaker import generate_schedule_overview


class InfoGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="info", description="Information about the tournament and your participation.")

    @app_commands.command(
        name="team",
        description="Shows your current team and availability.",
    )
    async def my_team(self, interaction: Interaction):
        """Displays the user's team and availability information."""
        tournament = load_tournament_data()
        user_mention = interaction.user.mention

        # Search for team membership
        for t_name, t_data in tournament.get("teams", {}).items():
            if user_mention in t_data.get("members", []):
                embed = Embed(
                    title="🏆 Your Tournament Info",
                    description=f"You are part of **{t_name}**!",
                    color=discord.Color.blue(),
                )
                embed.add_field(
                    name="General Availability",
                    value=t_data.get("availability", "No information"),
                    inline=False,
                )
                embed.add_field(
                    name="Saturday",
                    value=t_data.get("saturday", "No information"),
                    inline=True,
                )
                embed.add_field(
                    name="Sunday",
                    value=t_data.get("sunday", "No information"),
                    inline=True,
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        # Search for solo
        for solo in tournament.get("solo", []):
            if solo.get("player") == user_mention:
                embed = Embed(
                    title="🎯 Your Tournament Info",
                    description="You are registered as a **solo player**.",
                    color=discord.Color.orange(),
                )
                embed.add_field(
                    name="General Availability",
                    value=solo.get("availability", "No information"),
                    inline=False,
                )
                embed.add_field(
                    name="Saturday",
                    value=solo.get("saturday", "No information"),
                    inline=True,
                )
                embed.add_field(
                    name="Sunday",
                    value=solo.get("sunday", "No information"),
                    inline=True,
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        # Nothing found
        embed = Embed(
            title="🚫 No Registration Found",
            description="You are currently **not registered for this tournament**.",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="match_schedule", description="Shows the current match schedule.")
    async def match_schedule(self, interaction: Interaction):
        """Displays the tournament match schedule."""
        tournament = load_tournament_data()
        matches = tournament.get("matches", [])

        if not matches:
            await interaction.response.send_message("⚠️ No schedule available.", ephemeral=True)
            return

        description_text = generate_schedule_overview(matches)
        await send_match_schedule(interaction, description_text)

    @app_commands.command(
        name="help",
        description="Shows all important information and commands for HeroldBot.",
    )
    async def help_command(self, interaction: Interaction):
        """
        Displays the help embed.
        """
        await send_help(interaction)

    @app_commands.command(name="list_games", description="Shows all publicly selectable games.")
    async def list_games(self, interaction: Interaction):
        """Lists all games available for voting."""
        from modules.dataStorage import load_games

        games = load_games()
        if not games:
            await interaction.response.send_message("⚠️ No games are currently registered.", ephemeral=True)
            return

        # Only show games that are set to visible
        public_games = {
            gid: g for gid, g in games.items()
            if g.get("visible_in_poll", True) is True  # Default: visible
        }

        if not public_games:
            await interaction.response.send_message("⚠️ No games are currently publicly visible.", ephemeral=True)
            return

        embed = Embed(
            title="🎮 Available Games",
            description="Here are all games currently available for selection:",
            color=discord.Color.green(),
        )

        for game_id, game in public_games.items():
            name = game.get("name", "Unnamed")
            genre = game.get("genre", "–")
            platform = game.get("platform", "–")
            emoji = game.get("emoji", "🎮")
            team_size = game.get("team_size", game.get("min_players_per_team", 1))
            duration = game.get("match_duration_minutes", 60)
            pause = game.get("pause_minutes", 30)

            field_text = (
                f"• Genre: **{genre}**\n"
                f"• Platform: **{platform}**\n"
                f"• Team size: **{team_size}v{team_size}**\n"
                f"• Match duration: **~{duration} min** (+{pause} min pause)"
            )

            embed.add_field(name=f"{emoji} {name}", value=field_text, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


class InfoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.tree.add_command(InfoGroup())


async def setup(bot):
    await bot.add_cog(InfoCog(bot))
