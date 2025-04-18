# scripts/poll.py

import asyncio
import random
from datetime import datetime, timedelta
import discord
from discord import ButtonStyle, Interaction, TextChannel
from discord.ui import View, Button

from .dataStorage import load_tournament_data, save_tournament_data, load_global_data
from .logger import setup_logger
from .embeds import send_registration_open, create_embed_from_config
from .utils import has_permission

# Setup Logger
logger = setup_logger()

class PollView(View):
    def __init__(self, options: list, registration_period: int = 604800):
        super().__init__(timeout=None)
        self.votes = {}
        self.message = None
        self.options = [option for option in options if option.strip()]  # Leere Optionen entfernen
        self.results = {i: 0 for i in range(len(self.options))}
        self.registration_period = registration_period

        for i, option in enumerate(self.options):
            button = Button(label=option, custom_id=f"poll_{i}", style=ButtonStyle.primary)
            button.callback = self.make_callback(i, option)
            self.add_item(button)

        end_button = Button(label="🛑 Poll beenden", style=ButtonStyle.danger, custom_id="end_poll")
        end_button.callback = self.end_poll
        self.add_item(end_button)

    def make_callback(self, index: int, option: str):
        async def callback(interaction: Interaction):
            user_id = interaction.user.id

            # Hat der User schon gewählt?
            previous_vote = self.votes.get(user_id)
            if previous_vote is not None:
                self.results[previous_vote] -= 1  # Alte Stimme entfernen

            # Neue Stimme eintragen
            self.votes[user_id] = index
            self.results[index] += 1

            await interaction.response.send_message(f"✅ Deine Stimme für **{option}** wurde gespeichert!", ephemeral=True)
        return callback

    async def end_poll(self, interaction: Interaction):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung, die Umfrage zu beenden.", ephemeral=True)
            return

        tournament = load_tournament_data()

        if tournament.get("registration_open", False):
            await interaction.response.send_message("⚠️ Die Umfrage wurde bereits beendet und die Anmeldung ist offen.", ephemeral=True)
            return

        # Ergebnisse auswerten
        poll_result_mapping = {self.options[i]: count for i, count in self.results.items()}
        sorted_games = sorted(poll_result_mapping.items(), key=lambda kv: kv[1], reverse=True)

        if not sorted_games or sorted_games[0][1] == 0:
            chosen_game = "Keine Stimmen abgegeben"
        else:
            max_votes = sorted_games[0][1]
            top_games = [game for game, votes in sorted_games if votes == max_votes]
            chosen_game = random.choice(top_games)

            if len(top_games) > 1:
                logger.info(f"[POLL] Gleichstand bei {max_votes} Stimmen. Zufällig gewählt: {chosen_game}")
            else:
                logger.info(f"[POLL] Spiel gewählt: {chosen_game} ({max_votes} Stimmen)")

         # Hole die bereits gespeicherte Registrierung-Endzeit
        registration_end_str = tournament.get("registration_end")
        if registration_end_str:
            registration_end = datetime.fromisoformat(registration_end_str)
        else:
            registration_end = datetime.now() + timedelta(hours=48)  # Fallback, falls irgendwas schiefging

        # Update der Tournament-Daten
        tournament["poll_results"] = poll_result_mapping
        tournament["poll_results"]["chosen_game"] = chosen_game
        tournament["registration_open"] = True
        save_tournament_data(tournament)

        # Logger mit richtiger Zeit
        logger.info(f"[POLL] Poll beendet – Registrierung offen bis {registration_end.strftime('%d.%m.%Y %H:%M')}.")

        # Poll-Result-Embed senden
        embed_template = create_embed_from_config("POLL_RESULT_EMBED")
        for game, votes in sorted_games:
            embed_template.add_field(name=game, value=f"**{votes} Stimmen**", inline=False)

        if sorted_games and sorted_games[0][1] > 0:
            embed_template.add_field(name="🏆 Gewonnen", value=f"**{chosen_game}**", inline=False)

        await interaction.channel.send(embed=embed_template)

        # Anmelde-Embed senden
        formatted_end = registration_end.strftime("%d.%m.%Y %H:%M")
        await send_registration_open(interaction.channel, {"PLACEHOLDER_ENDTIME": formatted_end})

        # Abschlussmeldung
        #await interaction.response.send_message("✅ Umfrage erfolgreich beendet. Anmeldung ist jetzt offen!", ephemeral=True)
