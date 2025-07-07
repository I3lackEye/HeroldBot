from typing import Optional

import discord
from discord import Embed, Interaction, Member, app_commands
from discord.ext import commands
from discord.ui import Modal, TextInput

# Lokale Module
from modules.dataStorage import config, load_tournament_data, save_tournament_data
from modules.embeds import (
    send_participants_overview,
    send_registration_confirmation,
    send_wrong_channel,
)
from modules.logger import logger
from modules.modals import TeamFullJoinModal
from modules.reschedule import (
    handle_request_reschedule,
    match_id_autocomplete,
    neuer_zeitpunkt_autocomplete,
)
from modules.utils import (
    generate_team_name,
    has_permission,
    intersect_availability,
    parse_availability,
    validate_string,
)

# ----------------------------------------
# Slash-Commandsu
# ----------------------------------------
class PlayerGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="player", description="Befehle für Spieleranmeldung und Verfügbarkeit.")

    @app_commands.command(
        name="update_availability",
        description="Aktualisiere deine Verfügbarkeiten für das Turnier.",
    )
    @app_commands.describe(
        verfugbarkeit="Allgemeine Verfügbarkeit (z.B. 10:00-20:00)",
        samstag="Verfügbarkeit am Samstag (z.B. 12:00-18:00)",
        sonntag="Verfügbarkeit am Sonntag (z.B. 08:00-22:00)",
    )
    async def update_availability(
        self,
        interaction: Interaction,
        verfugbarkeit: Optional[str] = None,
        samstag: Optional[str] = None,
        sonntag: Optional[str] = None,
    ):
        """
        Aktualisiert die Verfügbarkeit eines Spielers im Turnier.
        Mindestens einer der Parameter (verfugbarkeit, samstag oder sonntag) muss angegeben werden.
        """
        if not any([verfugbarkeit, samstag, sonntag]):
            await interaction.response.send_message(
                "⚠️ Bitte gib mindestens eine Verfügbarkeit an (verfugbarkeit, samstag oder sonntag).",
                ephemeral=True,
            )
            return

        # Verfügbarkeiten prüfen
        try:
            if verfugbarkeit:
                parse_availability(verfugbarkeit)
            if samstag:
                parse_availability(samstag)
            if sonntag:
                parse_availability(sonntag)
        except ValueError as e:
            await interaction.response.send_message(f"🚫 Ungültiges Format: {str(e)}", ephemeral=True)
            return

        # Turnierdaten laden
        tournament = load_tournament_data()
        updated = False

        # Solo-Teilnehmer aktualisieren
        for entry in tournament.get("solo", []):
            if entry["player"] == interaction.user.mention:
                if verfugbarkeit:
                    entry["verfügbarkeit"] = verfugbarkeit
                if samstag:
                    entry["samstag"] = samstag
                if sonntag:
                    entry["sonntag"] = sonntag
                updated = True
                break

        # Team-Mitglieder aktualisieren
        for team_data in tournament.get("teams", {}).values():
            if interaction.user.mention in team_data.get("members", []):
                if verfugbarkeit:
                    team_data["verfügbarkeit"] = verfugbarkeit
                if samstag:
                    team_data["samstag"] = samstag
                if sonntag:
                    team_data["sonntag"] = sonntag
                updated = True
                break

        if not updated:
            await interaction.response.send_message(
                "⚠️ Du bist aktuell in keinem Team oder auf der Solo-Liste eingetragen.",
                ephemeral=True,
            )
            return

        save_tournament_data(tournament)
        await interaction.response.send_message(
            "✅ Deine Verfügbarkeit wurde erfolgreich aktualisiert!", ephemeral=True
        )

    @app_commands.command(name="leave", description="Melde dich vom Turnier ab.")
    async def leave(self, interaction: Interaction):
        """
        Meldet den User vom Turnier ab.
        """

        tournament = load_tournament_data()

        if not tournament.get("running", False):
            await interaction.response.send_message("Momentan läuft kein Turnier.", ephemeral=True)
            return

        user_mention = interaction.user.mention
        user_name = interaction.user.display_name
        found_team = None
        found_team_entry = None

        for team, team_entry in tournament.get("teams", {}).items():
            if user_mention in team_entry.get("members", []):
                found_team = team
                found_team_entry = team_entry
                break

        if found_team:
            if tournament.get("registration_open", False):
                other_members = [m for m in found_team_entry.get("members", []) if m != user_mention]
                del tournament["teams"][found_team]
                if other_members:
                    verfugbarkeit = found_team_entry.get("verfügbarkeit", "")
                    tournament.setdefault("solo", []).append(
                        {"player": other_members[0], "verfügbarkeit": verfugbarkeit}
                    )

                    # Namen auflösen
                    other_id = int(other_members[0].strip("<@>"))
                    other_member = interaction.guild.get_member(other_id)
                    other_name = other_member.display_name if other_member else other_members[0]

                    logger.info(f"[LEAVE] {other_name[0]} wurde aus Team {found_team} in die Solo-Liste übernommen.")
                save_tournament_data(tournament)
                logger.info(f"[LEAVE] {user_name} hat Team {found_team} verlassen. Team wurde aufgelöst.")
                await interaction.response.send_message(
                    f"✅ Du wurdest erfolgreich von Team {found_team} abgemeldet.",
                    ephemeral=True,
                )
                return
            else:
                del tournament["teams"][found_team]
                save_tournament_data(tournament)
                logger.info(f"[LEAVE] {user_name} hat Team {found_team} verlassen. Turnier war bereits geschlossen.")
                await interaction.response.send_message(f"✅ Dein Team {found_team} wurde entfernt.", ephemeral=True)
                return

        for entry in tournament.get("solo", []):
            if entry.get("player") == user_mention:
                tournament["solo"].remove(entry)
                save_tournament_data(tournament)
                logger.info(f"[LEAVE] Solo-Spieler {user_name} wurde erfolgreich abgemeldet.")
                await interaction.response.send_message(
                    "✅ Du wurdest erfolgreich aus der Solo-Liste entfernt.",
                    ephemeral=True,
                )
                return

        logger.warning(f"[LEAVE] {user_name} wollte sich abmelden, wurde aber nicht gefunden.")
        await interaction.response.send_message(
            "⚠ Du bist weder in einem Team noch in der Solo-Liste angemeldet.",
            ephemeral=True,
        )

    @app_commands.command(name="participants", description="Liste aller Teilnehmer anzeigen.")
    async def participants(self, interaction: Interaction):
        """
        Listet alle aktuellen Teilnehmer (Teams und Einzelspieler), alphabetisch sortiert.
        """
        tournament = load_tournament_data()

        teams = tournament.get("teams", {})
        solo = tournament.get("solo", [])

        # Teams alphabetisch sortieren
        sorted_teams = sorted(teams.items(), key=lambda x: x[0].lower())

        # Solo-Spieler alphabetisch sortieren (nach Mention)
        sorted_solo = sorted(solo, key=lambda x: x.get("player", "").lower())

        team_lines = []
        for name, team_entry in sorted_teams:
            members = ", ".join(team_entry.get("members", []))
            ver = team_entry.get("verfügbarkeit", {})
            samstag = ver.get("samstag", "-")
            sonntag = ver.get("sonntag", "-")
            team_lines.append(f"- {name}: {members}\n Samstag: {samstag}, Sonntag: {sonntag}\n")

        solo_lines = []
        for solo_entry in sorted_solo:
            solo_lines.append(f"- {solo_entry.get('player')}")

        # Text zusammensetzen
        full_text = ""

        if team_lines:
            full_text += "**Teams:**\n" + "\n".join(team_lines) + "\n\n"

        if solo_lines:
            full_text += "**Einzelspieler:**\n" + "\n".join(solo_lines)

        if not full_text:
            await interaction.response.send_message("❌ Es sind noch keine Teilnehmer angemeldet.", ephemeral=True)
        else:
            await send_participants_overview(interaction, full_text)

    @app_commands.command(name="join", description="Melde dich solo oder als Team zum Turnier an")
    async def join(self, interaction: Interaction):
        modal = TeamFullJoinModal()
        await interaction.response.send_modal(modal)

    """
    @app_commands.command(name="join", description="Melde dich solo oder als Team zum Turnier an")
    async def join(self, interaction: Interaction):
        view = AnmeldungChoiceView()
        await interaction.response.send_message("Wähle deine Anmeldeart:", view=view, ephemeral=True)
    """

    @app_commands.command(
        name="request_reschedule",
        description="Fordere eine Neuansetzung für ein Match an.",
    )
    @app_commands.autocomplete(match_id=match_id_autocomplete, neuer_zeitpunkt=neuer_zeitpunkt_autocomplete)
    async def request_reschedule(self, interaction: Interaction, match_id: int, neuer_zeitpunkt: str):
        await handle_request_reschedule(interaction, match_id, neuer_zeitpunkt)


class PlayerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.tree.add_command(PlayerGroup())


async def setup(bot: commands.Bot):
    await bot.add_cog(PlayerCog(bot))
