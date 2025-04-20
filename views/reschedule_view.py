from discord import ui, Interaction, Embed, Color
from discord import ButtonStyle

# Lokale Module
from modules.dataStorage import load_tournament_data, save_tournament_data


# ---------------------------------------
# View für Reschedule Buttons
# ---------------------------------------
class RescheduleView(ui.View):
    def __init__(self, match_id: int, team1: str, team2: str, players: list[str], new_datetime: str):
        super().__init__(timeout=86400)  # 24 Stunden
        self.match_id = match_id
        self.team1 = team1
        self.team2 = team2
        self.players = players
        self.new_datetime = new_datetime
        self.approved = set()
        self.message = None  # wird nach dem Senden gesetzt!

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.mention not in self.players:
            await interaction.response.send_message("🚫 Du bist nicht berechtigt, diese Anfrage zu bearbeiten.", ephemeral=True)
            return False
        return True

    @ui.button(label="✅ Akzeptieren", style=ButtonStyle.success)
    async def accept(self, interaction: Interaction, button: ui.Button):
        self.approved.add(interaction.user.mention)
        await interaction.response.send_message("✅ Zustimmung gespeichert.", ephemeral=True)

        if set(self.players) == self.approved:
            await self.success(interaction)

    @ui.button(label="❌ Ablehnen", style=ButtonStyle.danger)
    async def decline(self, interaction: Interaction, button: ui.Button):
        await self.abort(interaction, reason="Ein Spieler hat abgelehnt.")

    async def on_timeout(self):
        if self.message:
            await self.abort(None, reason="24h Frist überschritten.")

    async def success(self, interaction: Interaction):
        tournament = load_tournament_data()
        match = next((m for m in tournament.get("matches", []) if m.get("match_id") == self.match_id), None)

        if match:
            match["scheduled_time"] = self.new_datetime
            save_tournament_data(tournament)

        embed = Embed(
            title="🎉 Reschedule Erfolgreich!",
            description=f"Match **{self.team1} vs {self.team2}** verschoben auf **{self.new_datetime}**.",
            color=Color.green()
        )
        if self.message:
            await self.message.edit(embed=embed, view=None)

    async def abort(self, interaction: Interaction, reason: str):
        embed = Embed(
            title="❌ Reschedule Abgebrochen",
            description=reason,
            color=Color.red()
        )
        if self.message:
            await self.message.edit(embed=embed, view=None)

        if interaction:
            await interaction.response.send_message("🚫 Anfrage abgebrochen.", ephemeral=True)