from discord import ui, Interaction, Embed, Color
from discord import ButtonStyle
import discord
from datetime import datetime, timedelta

# Lokale Module
from modules.dataStorage import load_tournament_data, save_tournament_data
from modules.shared_states import pending_reschedules
from modules.logger import logger


# ---------------------------------------
# View für Reschedule Buttons
# ---------------------------------------

class RescheduleView(ui.View):
    def __init__(self, match_id: int, team1: str, team2: str, new_datetime: datetime, players: List[discord.Member]):
        super().__init__(timeout=86400)  # 24 Stunden

        self.match_id = match_id
        self.team1 = team1
        self.team2 = team2
        self.players = players  # <- Die übergebene Liste
        self.new_datetime = new_datetime

        self.pending_players = set(players)  # Alle Mitglieder, die noch zustimmen müssen
        self.approved = set()
        self.message = None


    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.mention not in self.players:
            await interaction.response.send_message("🚫 Du bist nicht berechtigt, diese Anfrage zu bearbeiten.", ephemeral=True)
            return False
        return True

    @ui.button(label="✅ Akzeptieren", style=ButtonStyle.success)
    async def accept(self, interaction: Interaction, button: ui.Button):
        self.pending_players.discard(interaction.user)
        self.approved.add(interaction.user.mention)

        logger.info(f"[RESCHEDULE] {interaction.user.display_name} ({interaction.user.id}) hat Reschedule für Match {self.match_id} bestätigt.")

        if self.pending_players:
            logger.info(f"[RESCHEDULE] Noch ausstehend: {', '.join(m.mention for m in self.pending_players)}")
        else:
            logger.info("[RESCHEDULE] Alle Spieler haben bestätigt.")

        await self.disable_buttons_for_user(interaction)
        await interaction.response.send_message("✅ Zustimmung gespeichert.", ephemeral=True)

        if not self.pending_players:
            await self.success(interaction)

    @ui.button(label="❌ Ablehnen", style=ButtonStyle.danger)
    async def decline(self, interaction: Interaction, button: ui.Button):
        logger.info(f"[RESCHEDULE] {interaction.user.display_name} ({interaction.user.id}) hat Reschedule für Match {self.match_id} abgelehnt.")
        self.declined.add(interaction.user.mention)
        await self.disable_buttons_for_user(interaction)
        await self.abort(interaction, reason="Ein Spieler hat abgelehnt.")
    
    async def disable_buttons_for_user(self, interaction: Interaction):
        # Neue Mini-View nur für diesen User bauen
        new_view = RescheduleView(
            match_id=self.match_id,
            team1=self.team1,
            team2=self.team2,
            players=self.players,
            new_datetime=self.new_datetime
        )
        for item in new_view.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True  # Buttons deaktivieren

        await interaction.message.edit(view=new_view)

    async def on_timeout(self):
        if self.message:
            await self.abort(None, reason="24h Frist überschritten.")

    async def success(self, interaction: Interaction):
        tournament = load_tournament_data()
        match = next((m for m in tournament.get("matches", []) if m.get("match_id") == self.match_id), None)

        if match:
            logger.info(f"[RESCHEDULE] Vor Änderung: {match}")
            match["scheduled_time"] = self.new_datetime.isoformat()
            save_tournament_data(tournament)
            logger.info(f"[RESCHEDULE] Nach Änderung gespeichert: {match}")

        pending_reschedules.discard(self.match_id)

        embed = Embed(
            title="🎉 Reschedule Erfolgreich!",
            description=f"Match **{self.team1} vs {self.team2}** verschoben auf **{self.new_datetime}**.",
            color=Color.green()
        )
        if self.message:
            await self.message.edit(embed=embed, view=None)

    async def abort(self, interaction: Interaction, reason: str):
        pending_reschedules.discard(self.match_id)
        embed = Embed(
            title="❌ Reschedule Abgebrochen",
            description=reason,
            color=Color.red()
        )
        if self.message:
            await self.message.edit(embed=embed, view=None)

        if interaction:
            await interaction.response.send_message("🚫 Anfrage abgebrochen.", ephemeral=True)

    async def on_timeout(self):
        # Wenn nach 24 Stunden niemand oder nicht alle bestätigt haben
        if self.message:
            await self.abort(reason="⌛ Zeit abgelaufen. Die Anfrage wurde automatisch beendet.")
