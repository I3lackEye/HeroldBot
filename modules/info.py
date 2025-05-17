# modules/info.py

import discord

from datetime import datetime
from discord import app_commands, Interaction, Embed
from discord.ext import commands

# Lokale Module
from modules.dataStorage import load_tournament_data
from modules.embeds import send_participants_overview, send_match_schedule, send_help
from modules.matchmaker import generate_schedule_overview

class InfoGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="info", description="Infos über das Turnier und deine Teilnahme.")

    @app_commands.command(name="team", description="Zeigt dir dein aktuelles Team und deine Verfügbarkeiten.")
    async def my_team(self, interaction: Interaction):
        tournament = load_tournament_data()
        user_mention = interaction.user.mention

        # Suche nach Teammitgliedschaft
        for t_name, t_data in tournament.get("teams", {}).items():
            if user_mention in t_data.get("members", []):
                embed = Embed(
                    title="🏆 Deine Turnier-Info",
                    description=f"Du bist Teil von **{t_name}**!",
                    color=discord.Color.blue()
                )
                embed.add_field(name="Allgemeine Verfügbarkeit", value=t_data.get("verfügbarkeit", "Keine Angabe"), inline=False)
                embed.add_field(name="Samstag", value=t_data.get("samstag", "Keine Angabe"), inline=True)
                embed.add_field(name="Sonntag", value=t_data.get("sonntag", "Keine Angabe"), inline=True)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        # Suche nach Solo
        for solo in tournament.get("solo", []):
            if solo.get("player") == user_mention:
                embed = Embed(
                    title="🎯 Deine Turnier-Info",
                    description="Du bist als **Einzelspieler** registriert.",
                    color=discord.Color.orange()
                )
                embed.add_field(name="Allgemeine Verfügbarkeit", value=solo.get("verfügbarkeit", "Keine Angabe"), inline=False)
                embed.add_field(name="Samstag", value=solo.get("samstag", "Keine Angabe"), inline=True)
                embed.add_field(name="Sonntag", value=solo.get("sonntag", "Keine Angabe"), inline=True)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        # Nichts gefunden
        embed = Embed(
            title="🚫 Keine Anmeldung gefunden",
            description="Du bist derzeit **nicht für dieses Turnier angemeldet**.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="participants", description="Liste aller Teilnehmer anzeigen.")
    async def participants(self, interaction: Interaction):
        """
        Listet alle aktuellen Teilnehmer (Teams und Einzelspieler), alphabetisch sortiert.
        """
        INVISIBLE_SPACE = "\u2800" #damit ordentlich umgebrochen wird... verfluchtes Discord
        tournament = load_tournament_data()

        teams = tournament.get("teams", {})
        solo = tournament.get("solo", [])

        # Teams alphabetisch sortieren
        sorted_teams = sorted(teams.items(), key=lambda x: x[0].lower())

        # Solo-Spieler alphabetisch sortieren (nach Mention)
        sorted_solo = sorted(solo, key=lambda x: x.get("player", "").lower())

        team_lines = []
        for name, team_entry in sorted_teams:
            # Mitglieder alphabetisch sortieren
            members = ", ".join(sorted(team_entry.get("members", [])))
            availability = team_entry.get("verfügbarkeit", "Keine Angabe")
            samstag = team_entry.get("samstag")
            sonntag = team_entry.get("sonntag")

            entry_text = f"- {name}: {members}\n{INVISIBLE_SPACE}🕒 Verfügbarkeit: **{availability}**"

            if samstag:
                entry_text += f"\n{INVISIBLE_SPACE}📅 Samstag: **{samstag}**"
            if sonntag:
                entry_text += f"\n{INVISIBLE_SPACE}📅 Sonntag: **{sonntag}**"

            team_lines.append(entry_text)

        solo_lines = []
        for solo_entry in sorted_solo:
            player = solo_entry.get('player')
            availability = solo_entry.get("verfügbarkeit", "Keine Angabe")
            samstag = solo_entry.get("samstag")
            sonntag = solo_entry.get("sonntag")

            # Hauptzeile
            entry_text = f"- {player}\n{INVISIBLE_SPACE}🕒 Verfügbarkeit: **{availability}**"

            # Samstag und Sonntag auf neue, schön eingerückte Zeilen
            if samstag:
                entry_text += f"\n{INVISIBLE_SPACE}📅 Samstag: **{samstag}**"
            if sonntag:
                entry_text += f"\n{INVISIBLE_SPACE}📅 Sonntag: **{sonntag}**"

            solo_lines.append(entry_text)


        # Text zusammensetzen
        full_text = ""

        if team_lines:
            full_text += "**Teams:**\n" + "\n".join(team_lines) + "\n\n"

        if solo_lines:
            full_text += "**Einzelspieler:**\n" + "\n".join(solo_lines)

        if not full_text:
            await interaction.response.send_message("❌ Es sind noch keine Teilnehmer angemeldet.", ephemeral=True)
            return

        # 🕒 Jetzt dynamische aktuelle Zeit erzeugen
        now = datetime.now().strftime("%d.%m.%Y, %H:%M Uhr")

        # Platzhalter einfügen
        full_text += f"\n\n*Letzte Aktualisierung: {now}*"

        # ✅ Teilnehmerübersicht senden
        await send_participants_overview(interaction, full_text)

    @app_commands.command(name="match_schedule", description="Zeigt den aktuellen Spielplan an.")
    async def match_schedule(self, interaction: Interaction):
        tournament = load_tournament_data()
        matches = tournament.get("matches", [])

        if not matches:
            await interaction.response.send_message("⚠️ Kein Spielplan vorhanden.", ephemeral=True)
            return

        description_text = generate_schedule_overview(matches)
        await send_match_schedule(interaction, description_text)

    @app_commands.command(name="help", description="Zeigt alle wichtigen Infos und Befehle zum HeroldBot an.")
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