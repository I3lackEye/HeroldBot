# modules/info.py

from datetime import datetime

import discord
from discord import Embed, Interaction, app_commands
from discord.ext import commands

# Lokale Module
from modules.dataStorage import load_tournament_data
from modules.embeds import send_help, send_match_schedule, send_participants_overview
from modules.matchmaker import generate_schedule_overview


class InfoGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="info", description="Infos über das Turnier und deine Teilnahme.")

    @app_commands.command(
        name="team",
        description="Zeigt dir dein aktuelles Team und deine Verfügbarkeiten.",
    )
    async def my_team(self, interaction: Interaction):
        tournament = load_tournament_data()
        user_mention = interaction.user.mention

        # Suche nach Teammitgliedschaft
        for t_name, t_data in tournament.get("teams", {}).items():
            if user_mention in t_data.get("members", []):
                embed = Embed(
                    title="🏆 Deine Turnier-Info",
                    description=f"Du bist Teil von **{t_name}**!",
                    color=discord.Color.blue(),
                )
                embed.add_field(
                    name="Allgemeine Verfügbarkeit",
                    value=t_data.get("verfügbarkeit", "Keine Angabe"),
                    inline=False,
                )
                embed.add_field(
                    name="Samstag",
                    value=t_data.get("samstag", "Keine Angabe"),
                    inline=True,
                )
                embed.add_field(
                    name="Sonntag",
                    value=t_data.get("sonntag", "Keine Angabe"),
                    inline=True,
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        # Suche nach Solo
        for solo in tournament.get("solo", []):
            if solo.get("player") == user_mention:
                embed = Embed(
                    title="🎯 Deine Turnier-Info",
                    description="Du bist als **Einzelspieler** registriert.",
                    color=discord.Color.orange(),
                )
                embed.add_field(
                    name="Allgemeine Verfügbarkeit",
                    value=solo.get("verfügbarkeit", "Keine Angabe"),
                    inline=False,
                )
                embed.add_field(
                    name="Samstag",
                    value=solo.get("samstag", "Keine Angabe"),
                    inline=True,
                )
                embed.add_field(
                    name="Sonntag",
                    value=solo.get("sonntag", "Keine Angabe"),
                    inline=True,
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        # Nichts gefunden
        embed = Embed(
            title="🚫 Keine Anmeldung gefunden",
            description="Du bist derzeit **nicht für dieses Turnier angemeldet**.",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="match_schedule", description="Zeigt den aktuellen Spielplan an.")
    async def match_schedule(self, interaction: Interaction):
        tournament = load_tournament_data()
        matches = tournament.get("matches", [])

        if not matches:
            await interaction.response.send_message("⚠️ Kein Spielplan vorhanden.", ephemeral=True)
            return

        description_text = generate_schedule_overview(matches)
        await send_match_schedule(interaction, description_text)

    @app_commands.command(
        name="help",
        description="Zeigt alle wichtigen Infos und Befehle zum HeroldBot an.",
    )
    async def help_command(self, interaction: Interaction):
        """
        Zeigt das Hilfe-Embed an.
        """
        await send_help(interaction)


class InfoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.tree.add_command(InfoGroup())


async def setup(bot):
    await bot.add_cog(InfoCog(bot))
