from typing import List
from datetime import datetime
import asyncio
import logging
import discord

from discord.ui import View, Button, Modal, TextInput
from discord import ButtonStyle, Interaction, Member

# Lokale Module
from modules.dataStorage import load_tournament_data, save_tournament_data
from modules.shared_states import pending_reschedules
from modules.logger import logger
from modules.modals import SoloJoinModal, TeamFullJoinModal, TestModal


class AnmeldungChoiceView(View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Solo", style=discord.ButtonStyle.primary, custom_id="anmeldung_solo")
    async def solo_button(self, interaction: Interaction, button: Button):
        logger.info(f"Button Solo geklickt")
        await interaction.response.send_modal(SoloJoinModal())

    @discord.ui.button(label="Team", style=discord.ButtonStyle.success, custom_id="anmeldung_team")
    async def team_button(self, interaction: Interaction, button: Button):
        logger.info(f"Button Team geklickt")
        await interaction.response.send_modal(TeamFullJoinModal()) 

    @discord.ui.button(label="Test", style=discord.ButtonStyle.primary)
    async def test_button(self, interaction, button):
        print("Testbutton wurde geklickt!")
        await interaction.response.send_modal(TestModal())
