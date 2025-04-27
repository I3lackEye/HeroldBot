from discord import ui, ButtonStyle, Interaction, Member
from typing import List
from datetime import datetime
import asyncio
import logging


# Lokale Module
from modules.dataStorage import load_tournament_data, save_tournament_data
from modules.shared_states import pending_reschedules
from modules.logger import logger


# ---------------------------------------
# View für Reschedule Buttons
# ---------------------------------------

class RescheduleView(ui.View):
    def __init__(self, match_id: int, team1: str, team2: str, new_datetime: datetime, players: List[Member]):
        super().__init__(timeout=86400)  # 24 Stunden
        self.match_id = match_id
        self.team1 = team1
        self.team2 = team2
        self.new_datetime = new_datetime
        self.players = players
        self.approved = set()
        self.message = None

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Nur erlaubte Spieler dürfen klicken."""
        return interaction.user in self.players

    @ui.button(label="✅ Akzeptieren", style=ButtonStyle.success)
    async def accept(self, interaction: Interaction, button: ui.Button):
        self.approved.add(interaction.user)

        if self.message:
            await interaction.response.defer()
        else:
            await interaction.response.send_message("✅ Zustimmung gespeichert.", ephemeral=True)

        logger.info(f"[RESCHEDULE] {interaction.user.display_name} hat Reschedule für Match {self.match_id} bestätigt.")

        if self.approved == set(self.players):
            await self.success(interaction)

    @ui.button(label="❌ Ablehnen", style=ButtonStyle.danger)
    async def decline(self, interaction: Interaction, button: ui.Button):
        if self.message:
            await interaction.response.defer()
        else:
            await interaction.response.send_message("❌ Ablehnung gespeichert.", ephemeral=True)

        logger.warning(f"[RESCHEDULE] {interaction.user.display_name} hat Reschedule für Match {self.match_id} abgelehnt.")
        await self.abort(interaction)

    async def success(self, interaction: Interaction):
        """Wenn alle zugestimmt haben: Match verschieben."""
        tournament = load_tournament_data()

        match = next((m for m in tournament.get("matches", []) if m.get("match_id") == self.match_id), None)
        if match:
            match["scheduled_time"] = self.new_datetime.isoformat()
            save_tournament_data(tournament)
            logger.info(f"[RESCHEDULE] Match {self.match_id} erfolgreich auf {self.new_datetime} verschoben.")

        pending_reschedules.discard(self.match_id)

        await self.message.edit(content=f"✅ Alle Spieler haben zugestimmt! Match {self.match_id} verschoben auf {self.new_datetime.strftime('%d.%m.%Y %H:%M')}!", embed=None, view=None)
        self.stop()

    async def abort(self, interaction: Interaction):
        """Wenn jemand ablehnt oder Timeout."""
        pending_reschedules.discard(self.match_id)

        await self.message.edit(content=f"❌ Reschedule-Anfrage für Match {self.match_id} abgebrochen.", embed=None, view=None)
        self.stop()

    async def on_timeout(self):
        """Timeout nach 24h."""
        logger.warning(f"[RESCHEDULE] Timeout für Match {self.match_id}. Anfrage automatisch abgebrochen.")
        if self.message:
            await self.message.edit(content=f"⌛ Reschedule-Anfrage für Match {self.match_id} ist abgelaufen.", embed=None, view=None)
        pending_reschedules.discard(self.match_id)
