#tournament.py
import discord
import asyncio
import logging
from discord.ui import View, Button
from datetime import datetime, timedelta
from .dataStorage import reset_tournament_data, load_global_data, load_tournament_data, save_tournament_data, load_config
from .logger import setup_logger
from .utils import has_permission
from .matchmaker import auto_match_solo

# Setup Logger
logger = setup_logger("logs", level=logging.INFO)

async def finalize_registration(interaction: discord.Interaction, registration_period: int):
    # Warte, bis die Registrierungszeit abgelaufen ist
    await asyncio.sleep(registration_period)
    
    # Setze das Flag "registration_open" auf False
    tournament = load_tournament_data()
    tournament["registration_open"] = False
    save_tournament_data(tournament)
    await interaction.channel.send("Die Anmeldephase ist nun geschlossen.")
    
    # Rufe die Funktion zum automatischen Zusammenführen der Solo-Spieler auf
    new_teams = auto_match_solo()
    
    # Sende eine Nachricht mit den neu gebildeten Teams
    if new_teams:
        msg_lines = ["Neue Teams aus der Solo-Anmeldung:"]
        for team, members in new_teams.items():
            msg_lines.append(f"**{team}**: {', '.join(members)}")
        msg = "\n".join(msg_lines)
    else:
        msg = "Es wurden keine neuen Teams gebildet (nicht genügend Spieler)."
    
    await interaction.channel.send(msg)
    logger.info("Automatisches Matchmaking durchgeführt.")

# PollView: Verwende Message Components (Buttons)
class PollView(View):
    def __init__(self, options: list, registration_period: int = 604800):  # ca. 7 Tage Anmeldungsfrist
        """
        :param options: Liste der Poll-Optionen (z.B. Spiele).
        :param registration_period: Dauer der Freigabe in Sekunden.
        """
        super().__init__(timeout=None)  # Kein Timeout
        self.message = None  # Attribut initialisieren
        self.options = options
        self.results = {i: 0 for i in range(len(options))}
        self.registration_period = registration_period
        for i, option in enumerate(options):
            button = Button(label=option, custom_id=f"poll_{i}", style=discord.ButtonStyle.primary)
            button.callback = self.make_callback(i, option)
            self.add_item(button)
        # Button, um den Poll zu beenden
        end_button = Button(label="Poll beenden", style=discord.ButtonStyle.danger, custom_id="end_poll")
        end_button.callback = self.end_poll
        self.add_item(end_button)

    def make_callback(self, index: int, option: str):
        async def callback(interaction: discord.Interaction):
            self.results[index] += 1
            await interaction.response.send_message(f"Du hast für **{option}** gestimmt!", ephemeral=True)
        return callback

    async def end_poll(self, interaction: discord.Interaction):
        # Ergebnisse zusammenfassen
        result_text = "Poll-Ergebnisse:\n"
        for i, count in self.results.items():
            result_text += f"{self.options[i]}: {count} Stimmen\n"
        
        await interaction.response.send_message(result_text, ephemeral=False)

        # Ergebnisse umwandeln: Erstelle ein neues Dictionary, in dem die Optionen (Strings) als Schlüssel dienen.
        poll_result_mapping = {self.options[i]: count for i, count in self.results.items()}
        
        # Ergebnisse speichern etc.
        tournament = load_tournament_data()
        tournament["poll_results"] = poll_result_mapping
        save_tournament_data(tournament)
    
        logger.info("Poll beendet. Ergebnisse wurden gespeichert.")
    
         # Registrierung freigeben und Endzeitpunkt anzeigen
        tournament = load_tournament_data()
        tournament["registration_open"] = True
        save_tournament_data(tournament)
        end_time = datetime.now() + timedelta(seconds=self.registration_period)
        formatted_end = end_time.strftime("%d.%m.%Y %H:%M")
        await interaction.channel.send("Die Anmeldung ist bis {} freigegeben!".format(formatted_end))
    
        # Starte die Hintergrundaufgabe, die nach Ablauf der Frist die Anmeldung schließt und das Matchmaking ausführt
        async def close_registration_and_finalize():
            await asyncio.sleep(self.registration_period)
            # Schließe die Registrierung
            tournament = load_tournament_data()
            tournament["registration_open"] = False
            save_tournament_data(tournament)
            await interaction.channel.send("Die Anmeldephase ist nun geschlossen.")
            # Führe das Matchmaking durch: Forme Solo-Spieler zu Teams
            new_teams = auto_match_solo()
            if new_teams:
                msg_lines = ["Neue Teams aus der Solo-Anmeldung:"]
                for team, members in new_teams.items():
                    msg_lines.append(f"**{team}**: {', '.join(members)}")
                msg = "\n".join(msg_lines)
            else:
                msg = "Es konnten keine neuen Teams gebildet werden (nicht genügend Solo-Spieler)."
            await interaction.channel.send(msg)
            logger.info("Matchmaking abgeschlossen und Teams wurden gebildet.")

        asyncio.create_task(close_registration_and_finalize())
        self.stop()  # Beende die View

        # Lösche die Poll-Nachricht, falls vorhanden
        if self.message:
            try:
                await self.message.delete()
                logger.info("Poll-Nachricht wurde gelöscht.")
            except Exception as e:
                logger.error(f"Fehler beim Löschen der Poll-Nachricht: {e}")

# Funktion zum Starten eines Turniers inkl. Poll
async def start_tournament(interaction: discord.Interaction, registration_period: int = 604800):
    # Überprüfe auf Korrekten Channel
    if interaction.channel_id != CHANNEL_LIMIT_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        logger.info(f"User {interaction.user} hat falschen Channel für Command verwendet")
        return
    
    # Überprüfe, ob der Nutzer Administratorrechte hat.
    if not has_permission(interaction.user, "Moderator", "Admin"):
        logger.info(f"{interaction.user} hatte keine Berechtigung")
        await interaction.response.send_message("Du hast keine ausreichenden Rechte, um diesen Befehl auszuführen.", ephemeral=True)
        return

    tournament = load_tournament_data()
    if tournament.get("running", False):
        await interaction.response.send_message("Ein Turnier läuft bereits!", ephemeral=True)
        return

    # Setze das Turnier zurück und markiere es als laufend
    tournament = reset_tournament_data()
    tournament["running"] = True
    save_tournament_data(tournament)

    # Lade die globalen Spieldaten
    global_data = load_global_data()
    games = global_data.get("games", [])
    if not games:
        await interaction.response.send_message("Es sind keine Spiele in den globalen Daten hinterlegt.", ephemeral=True)
        return

    # Erstelle die PollView mit der angegebenen Registrierungsdauer (in Sekunden)
    view = PollView(games, registration_period=registration_period)
    poll_msg = await interaction.channel.send("Bitte stimme ab, welches Spiel im Turnier gespielt werden soll:", view=view)
    view.message = poll_msg

    # Sende eine Bestätigung (optional auch mit Anzeige des Endzeitpunkts)
    end_time = datetime.now() + timedelta(seconds=registration_period)
    formatted_end = end_time.strftime("%d.%m.%Y %H:%M")
    await interaction.response.send_message(f"Neues Turnier gestartet. Die Anmeldung ist bis {formatted_end} freigegeben.", ephemeral=True)